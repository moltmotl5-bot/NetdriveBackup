from __future__ import annotations

import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable

from nccm.backup.runner import run_backup_job
from nccm.models import BackupResult, DeviceRow


@dataclass
class BackupJob:
    job_id: str
    status: str  # queued | running | done | failed
    logs: list[str] = field(default_factory=list)
    result_run_id: str | None = None
    results: list[BackupResult] | None = None
    error: str | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def append_log(self, line: str) -> None:
        with self._lock:
            self.logs.append(line)

    def snapshot(self, log_from: int = 0) -> tuple[list[str], str, dict | None]:
        with self._lock:
            lines = self.logs[log_from:]
            status = self.status
            if status not in ("done", "failed"):
                return lines, status, None
            payload = {
                "status": status,
                "result_run_id": self.result_run_id,
                "error": self.error,
                "results": [asdict(r) for r in (self.results or [])],
            }
            return lines, status, payload


_jobs: dict[str, BackupJob] = {}
_jobs_lock = threading.Lock()
_MAX_JOBS = 30


def _prune_jobs() -> None:
    with _jobs_lock:
        if len(_jobs) <= _MAX_JOBS:
            return
        oldest = sorted(_jobs.values(), key=lambda j: j.created_at)[: len(_jobs) - _MAX_JOBS]
        for j in oldest:
            _jobs.pop(j.job_id, None)


def get_job(job_id: str) -> BackupJob | None:
    with _jobs_lock:
        return _jobs.get(job_id)


def start_backup_job_async(
    devices: list[DeviceRow],
    *,
    username: str,
    password: str,
    enable_password: str = "",
    agent_url: str | None = None,
) -> str:
    job_id = str(uuid.uuid4())
    job = BackupJob(job_id=job_id, status="queued")
    with _jobs_lock:
        _jobs[job_id] = job
    _prune_jobs()

    def worker() -> None:
        job.status = "running"
        job.append_log(f"Job {job_id} started ({len(devices)} devices)")

        def log(msg: str) -> None:
            job.append_log(msg)

        try:
            run_id, results = run_backup_job(
                devices,
                username=username,
                password=password,
                enable_password=enable_password,
                agent_url=agent_url,
                log=log,
            )
            job.result_run_id = run_id
            job.results = results
            job.status = "done"
            ok = sum(1 for r in results if r.status == "ok")
            job.append_log(f"Job finished: {ok}/{len(results)} ok (run_id={run_id})")
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
            job.append_log(f"Job failed: {exc}")
            job.results = job.results or []

    threading.Thread(target=worker, name=f"backup-{job_id[:8]}", daemon=True).start()
    return job_id