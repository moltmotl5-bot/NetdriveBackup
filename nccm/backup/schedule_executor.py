"""Execute scheduled live backups via shared backup runner."""
from __future__ import annotations

import fcntl
import tempfile
from pathlib import Path

from nccm.backup.job_manager import get_job, start_backup_job_async
from nccm.backup.schedule import (
    MODE_LIVE,
    _connect,
    _get_schedule_row,
    _utc_now,
    get_schedule,
    list_schedules,
    load_schedule_devices,
    resolve_schedule_credentials,
    schedule_lock_path,
)
from nccm.config import netdriver_url
from nccm.registry.csv import load_devices_csv


def _is_job_active(job_id: str) -> bool:
    if not job_id:
        return False
    job = get_job(job_id)
    if not job:
        return False
    return job.status in ("queued", "running")


def _insert_run(
    conn,
    *,
    schedule_id: int,
    mode: str,
    status: str,
    triggered_by: str,
    job_id: str = "",
    summary: str = "",
    device_count: int = 0,
) -> int:
    now = _utc_now()
    cur = conn.execute(
        """
        INSERT INTO schedule_runs (
            schedule_id, started_at, finished_at, mode, job_id, run_id,
            status, ok_count, fail_count, device_count, summary, triggered_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?)
        """,
        (
            int(schedule_id),
            now,
            now if status != "running" else None,
            mode,
            job_id,
            "",
            status,
            device_count,
            summary[:500],
            triggered_by,
        ),
    )
    return int(cur.lastrowid)


def _finish_run(
    conn,
    *,
    run_id: int,
    schedule_id: int,
    status: str,
    summary: str,
    job_id: str = "",
    run_id_backup: str = "",
    ok_count: int = 0,
    fail_count: int = 0,
    device_count: int = 0,
) -> None:
    now = _utc_now()
    conn.execute(
        """
        UPDATE schedule_runs SET
            finished_at = ?, status = ?, job_id = ?, run_id = ?,
            ok_count = ?, fail_count = ?, device_count = ?, summary = ?
        WHERE id = ?
        """,
        (
            now,
            status,
            job_id,
            run_id_backup,
            ok_count,
            fail_count,
            device_count,
            summary[:500],
            int(run_id),
        ),
    )
    conn.execute(
        """
        UPDATE schedules SET
            last_run_at = ?, last_result = ?, updated_at = ?,
            running_job_id = '', last_job_id = ?,
            last_ok_count = ?, last_fail_count = ?
        WHERE id = ?
        """,
        (
            now,
            summary[:500],
            now,
            job_id,
            ok_count,
            fail_count,
            int(schedule_id),
        ),
    )


def poll_running_jobs() -> list[dict]:
    """Finalize schedules whose async backup jobs have completed."""
    outcomes: list[dict] = []
    for sch in list_schedules():
        job_id = ""
        with _connect() as conn:
            row = _get_schedule_row(conn, sch.id)
            if not row:
                continue
            job_id = str(row["running_job_id"] or "")
        if not job_id:
            continue
        job = get_job(job_id)
        if not job or job.status in ("queued", "running"):
            continue
        with _connect() as conn:
            row = _get_schedule_row(conn, sch.id)
            if not row:
                continue
            run_row = conn.execute(
                """
                SELECT id FROM schedule_runs
                WHERE schedule_id = ? AND job_id = ? AND status = 'running'
                ORDER BY id DESC LIMIT 1
                """,
                (sch.id, job_id),
            ).fetchone()
            if not run_row:
                conn.execute(
                    "UPDATE schedules SET running_job_id = '', updated_at = ? WHERE id = ?",
                    (_utc_now(), sch.id),
                )
                continue
            run_id = int(run_row["id"])
            if job.status == "done":
                results = job.results or []
                ok = sum(1 for r in results if r.status == "ok")
                fail = len(results) - ok
                summary = f"live ok {ok}/{len(results)} job={job_id[:8]}"
                _finish_run(
                    conn,
                    run_id=run_id,
                    schedule_id=sch.id,
                    status="done",
                    summary=summary,
                    job_id=job_id,
                    run_id_backup=job.result_run_id or "",
                    ok_count=ok,
                    fail_count=fail,
                    device_count=len(results),
                )
                outcomes.append({"schedule_id": sch.id, "ok": True, "summary": summary})
            else:
                summary = f"live failed job={job_id[:8]} {job.error or ''}"[:500]
                _finish_run(
                    conn,
                    run_id=run_id,
                    schedule_id=sch.id,
                    status="failed",
                    summary=summary,
                    job_id=job_id,
                    device_count=0,
                )
                outcomes.append({"schedule_id": sch.id, "ok": False, "summary": summary})
    return outcomes


def execute_schedule(
    schedule_id: int,
    *,
    triggered_by: str = "manual",
) -> dict:
    sch = get_schedule(schedule_id)
    if not sch:
        raise ValueError("schedule not found")

    with _connect() as conn:
        row = _get_schedule_row(conn, schedule_id)
        assert row
        running = str(row["running_job_id"] or "")
        if _is_job_active(running):
            run_id = _insert_run(
                conn,
                schedule_id=schedule_id,
                mode=MODE_LIVE,
                status="skipped",
                triggered_by=triggered_by,
                summary="previous job still running",
            )
            return {
                "ok": False,
                "skipped": True,
                "schedule_id": schedule_id,
                "run_id": run_id,
                "error": "前次備份仍在進行中",
            }

    try:
        creds = resolve_schedule_credentials(schedule_id)
    except ValueError as exc:
        with _connect() as conn:
            _insert_run(
                conn,
                schedule_id=schedule_id,
                mode=MODE_LIVE,
                status="failed",
                triggered_by=triggered_by,
                summary=str(exc)[:500],
            )
        return {"ok": False, "schedule_id": schedule_id, "error": str(exc)}

    devices = load_schedule_devices(sch)
    if not devices:
        return {"ok": False, "schedule_id": schedule_id, "error": "排程無設備"}

    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as tmp:
        tmp.write(sch.csv_text)
        csv_path = Path(tmp.name)
    try:
        device_rows = load_devices_csv(csv_path)
    finally:
        csv_path.unlink(missing_ok=True)

    job_id = start_backup_job_async(
        device_rows,
        username=creds.username,
        password=creds.password,
        enable_password=creds.enable_password,
        agent_url=netdriver_url(),
    )

    with _connect() as conn:
        run_id = _insert_run(
            conn,
            schedule_id=schedule_id,
            mode=MODE_LIVE,
            status="running",
            triggered_by=triggered_by,
            job_id=job_id,
            device_count=len(device_rows),
        )
        conn.execute(
            "UPDATE schedules SET running_job_id = ?, updated_at = ? WHERE id = ?",
            (job_id, _utc_now(), int(schedule_id)),
        )

    return {
        "ok": True,
        "async": True,
        "schedule_id": schedule_id,
        "job_id": job_id,
        "run_id": run_id,
        "device_count": len(device_rows),
        "message": f"備份已啟動（{len(device_rows)} 台）",
    }


class ScheduleLock:
    def __init__(self) -> None:
        self._fp = None

    def acquire(self) -> bool:
        path = schedule_lock_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fp = open(path, "a+", encoding="utf-8")
        try:
            fcntl.flock(self._fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self._fp.close()
            self._fp = None
            return False

    def release(self) -> None:
        if self._fp is not None:
            fcntl.flock(self._fp.fileno(), fcntl.LOCK_UN)
            self._fp.close()
            self._fp = None

    def __enter__(self) -> bool:
        return self.acquire()

    def __exit__(self, *args) -> None:
        self.release()
