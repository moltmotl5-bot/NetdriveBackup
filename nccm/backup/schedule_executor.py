"""Execute scheduled live backups via shared backup runner."""
from __future__ import annotations

import fcntl
import tempfile
from pathlib import Path

from nccm.backup.job_manager import BackupJob, get_job, start_backup_job_async
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

_STARTING = "__starting__"


def _is_job_active(job_id: str) -> bool:
    if not job_id or job_id == _STARTING:
        return True
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


def _finish_run_for_job(conn, *, schedule_id: int, run_id: int, job: BackupJob) -> None:
    job_id = job.job_id
    if job.status == "done":
        results = job.results or []
        ok = sum(1 for r in results if r.status == "ok")
        fail = len(results) - ok
        summary = f"live ok {ok}/{len(results)} job={job_id[:8]}"
        _finish_run(
            conn,
            run_id=run_id,
            schedule_id=schedule_id,
            status="done",
            summary=summary,
            job_id=job_id,
            run_id_backup=job.result_run_id or "",
            ok_count=ok,
            fail_count=fail,
            device_count=len(results),
        )
        return
    summary = f"live failed job={job_id[:8]} {job.error or ''}"[:500]
    _finish_run(
        conn,
        run_id=run_id,
        schedule_id=schedule_id,
        status="failed",
        summary=summary,
        job_id=job_id,
        device_count=0,
    )


def _finalize_orphan_run(
    conn,
    *,
    schedule_id: int,
    job_id: str,
    summary: str,
) -> None:
    row = conn.execute(
        """
        SELECT id FROM schedule_runs
        WHERE schedule_id = ? AND job_id = ? AND status = 'running'
        ORDER BY id DESC LIMIT 1
        """,
        (int(schedule_id), job_id),
    ).fetchone()
    if not row:
        conn.execute(
            "UPDATE schedules SET running_job_id = '', updated_at = ? WHERE id = ?",
            (_utc_now(), int(schedule_id)),
        )
        return
    now = _utc_now()
    conn.execute(
        """
        UPDATE schedule_runs SET
            finished_at = ?, status = 'failed', summary = ?
        WHERE id = ?
        """,
        (now, summary[:500], int(row["id"])),
    )
    conn.execute(
        """
        UPDATE schedules SET running_job_id = '', last_result = ?, updated_at = ?
        WHERE id = ?
        """,
        (summary[:500], now, int(schedule_id)),
    )


def _reconcile_schedule_running(conn, schedule_id: int, running_job_id: str) -> str:
    """Return 'busy', 'cleared', or 'idle'."""
    if not running_job_id:
        return "idle"
    if running_job_id == _STARTING:
        return "busy"

    job = get_job(running_job_id)
    if job and job.status in ("queued", "running"):
        return "busy"
    if job and job.status in ("done", "failed"):
        row = conn.execute(
            """
            SELECT id FROM schedule_runs
            WHERE schedule_id = ? AND job_id = ? AND status = 'running'
            ORDER BY id DESC LIMIT 1
            """,
            (int(schedule_id), running_job_id),
        ).fetchone()
        if row:
            _finish_run_for_job(conn, schedule_id=schedule_id, run_id=int(row["id"]), job=job)
        else:
            conn.execute(
                "UPDATE schedules SET running_job_id = '', updated_at = ? WHERE id = ?",
                (_utc_now(), int(schedule_id)),
            )
        return "cleared"

    _finalize_orphan_run(
        conn,
        schedule_id=schedule_id,
        job_id=running_job_id,
        summary=f"job record lost ({running_job_id[:8]})",
    )
    return "cleared"


def poll_running_jobs() -> list[dict]:
    """Finalize schedule_runs whose async backup jobs have completed."""
    outcomes: list[dict] = []
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, schedule_id, job_id
            FROM schedule_runs
            WHERE status = 'running' AND job_id != '' AND job_id != ?
            ORDER BY id
            """,
            (_STARTING,),
        ).fetchall()

    for row in rows:
        run_id = int(row["id"])
        schedule_id = int(row["schedule_id"])
        job_id = str(row["job_id"])
        job = get_job(job_id)
        if not job:
            with _connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                still = conn.execute(
                    "SELECT id FROM schedule_runs WHERE id = ? AND status = 'running'",
                    (run_id,),
                ).fetchone()
                if still:
                    _finalize_orphan_run(
                        conn,
                        schedule_id=schedule_id,
                        job_id=job_id,
                        summary=f"job record lost ({job_id[:8]})",
                    )
                    outcomes.append(
                        {
                            "schedule_id": schedule_id,
                            "ok": False,
                            "summary": f"job record lost ({job_id[:8]})",
                        }
                    )
            continue
        if job.status in ("queued", "running"):
            continue
        with _connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            still = conn.execute(
                "SELECT id FROM schedule_runs WHERE id = ? AND status = 'running'",
                (run_id,),
            ).fetchone()
            if not still:
                continue
            _finish_run_for_job(conn, schedule_id=schedule_id, run_id=run_id, job=job)
            ok = job.status == "done"
            summary = (
                f"live ok {sum(1 for r in (job.results or []) if r.status == 'ok')}/{len(job.results or [])} job={job_id[:8]}"
                if ok
                else f"live failed job={job_id[:8]} {job.error or ''}"[:500]
            )
            outcomes.append({"schedule_id": schedule_id, "ok": ok, "summary": summary})
    return outcomes


def _execute_schedule_body(
    schedule_id: int,
    *,
    triggered_by: str = "manual",
) -> dict:
    sch = get_schedule(schedule_id)
    if not sch:
        raise ValueError("schedule not found")

    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _get_schedule_row(conn, schedule_id)
        if not row:
            conn.rollback()
            raise ValueError("schedule not found")
        running = str(row["running_job_id"] or "")
        state = _reconcile_schedule_running(conn, schedule_id, running)
        if state == "busy":
            run_id = _insert_run(
                conn,
                schedule_id=schedule_id,
                mode=MODE_LIVE,
                status="skipped",
                triggered_by=triggered_by,
                summary="previous job still running",
            )
            conn.commit()
            return {
                "ok": False,
                "skipped": True,
                "schedule_id": schedule_id,
                "run_id": run_id,
                "error": "前次備份仍在進行中",
            }

        active = conn.execute(
            """
            SELECT id FROM schedule_runs
            WHERE schedule_id = ? AND status = 'running'
            LIMIT 1
            """,
            (int(schedule_id),),
        ).fetchone()
        if active:
            run_id = _insert_run(
                conn,
                schedule_id=schedule_id,
                mode=MODE_LIVE,
                status="skipped",
                triggered_by=triggered_by,
                summary="previous job still running",
            )
            conn.commit()
            return {
                "ok": False,
                "skipped": True,
                "schedule_id": schedule_id,
                "run_id": run_id,
                "error": "前次備份仍在進行中",
            }

        conn.execute(
            "UPDATE schedules SET running_job_id = ?, updated_at = ? WHERE id = ?",
            (_STARTING, _utc_now(), int(schedule_id)),
        )
        conn.commit()

    try:
        creds = resolve_schedule_credentials(schedule_id)
    except ValueError as exc:
        with _connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            _insert_run(
                conn,
                schedule_id=schedule_id,
                mode=MODE_LIVE,
                status="failed",
                triggered_by=triggered_by,
                summary=str(exc)[:500],
            )
            conn.execute(
                "UPDATE schedules SET running_job_id = '', updated_at = ? WHERE id = ?",
                (_utc_now(), int(schedule_id)),
            )
            conn.commit()
        return {"ok": False, "schedule_id": schedule_id, "error": str(exc)}

    devices = load_schedule_devices(sch)
    if not devices:
        with _connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE schedules SET running_job_id = '', updated_at = ? WHERE id = ?",
                (_utc_now(), int(schedule_id)),
            )
            conn.commit()
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
        conn.execute("BEGIN IMMEDIATE")
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
        conn.commit()

    return {
        "ok": True,
        "async": True,
        "schedule_id": schedule_id,
        "job_id": job_id,
        "run_id": run_id,
        "device_count": len(device_rows),
        "message": f"備份已啟動（{len(device_rows)} 台）",
    }


def execute_schedule(
    schedule_id: int,
    *,
    triggered_by: str = "manual",
) -> dict:
    lock = ScheduleLock()
    if not lock.acquire():
        return {
            "ok": False,
            "skipped": True,
            "schedule_id": schedule_id,
            "error": "排程鎖被占用（其他實例或 watcher 正在執行）",
        }
    try:
        poll_running_jobs()
        return _execute_schedule_body(schedule_id, triggered_by=triggered_by)
    finally:
        lock.release()


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
