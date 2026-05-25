from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import sqlite3
from uuid import uuid4

ACTIVE_STATUSES = {"running", "cancel_pending"}
ORPHANED_STATUS_NOTE = "server restarted while Hermes job was active"


@dataclass(frozen=True)
class HermesJob:
    id: str
    status: str
    task: str
    prompt: str
    profile: str
    profile_home: str
    stdout_path: str
    stderr_path: str
    progress_summary: str | None
    final_result: str | None
    delivery_status: str
    pid: int | None
    started_at: str
    finished_at: str | None
    status_note: str | None


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_job(row: sqlite3.Row | None) -> HermesJob | None:
    if row is None:
        return None
    return HermesJob(
        id=row["id"],
        status=row["status"],
        task=row["task"],
        prompt=row["prompt"],
        profile=row["profile"],
        profile_home=row["profile_home"],
        stdout_path=row["stdout_path"],
        stderr_path=row["stderr_path"],
        progress_summary=row["progress_summary"],
        final_result=row["final_result"],
        delivery_status=row["delivery_status"],
        pid=row["pid"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        status_note=row["status_note"],
    )


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _fetch_job(conn: sqlite3.Connection, job_id: str) -> HermesJob:
    job = _row_to_job(conn.execute("SELECT * FROM hermes_jobs WHERE id = ?", (job_id,)).fetchone())
    if job is None:
        raise ValueError(f"Hermes job not found: {job_id}")
    return job


def create_hermes_job(
    db_path: Path,
    *,
    task: str,
    prompt: str,
    profile: str,
    profile_home: Path,
    stdout_path: Path,
    stderr_path: Path,
) -> HermesJob:
    job_id = str(uuid4())
    with _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        active = conn.execute(
            "SELECT id FROM hermes_jobs WHERE status IN ('running', 'cancel_pending') LIMIT 1"
        ).fetchone()
        if active is not None:
            raise ValueError(f"active Hermes job already exists: {active['id']}")

        conn.execute(
            """
            INSERT INTO hermes_jobs (
                id, status, task, prompt, profile, profile_home, stdout_path, stderr_path
            )
            VALUES (?, 'running', ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                task,
                prompt,
                profile,
                str(profile_home),
                str(stdout_path),
                str(stderr_path),
            ),
        )
        conn.commit()
        return _fetch_job(conn, job_id)


def get_active_hermes_job(db_path: Path) -> HermesJob | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT * FROM hermes_jobs
            WHERE status IN ('running', 'cancel_pending')
            ORDER BY started_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
        return _row_to_job(row)


def get_latest_hermes_job(db_path: Path) -> HermesJob | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT * FROM hermes_jobs
            ORDER BY started_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
        return _row_to_job(row)


def set_hermes_job_pid(db_path: Path, job_id: str, pid: int) -> None:
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute("UPDATE hermes_jobs SET pid = ? WHERE id = ?", (pid, job_id))
        conn.commit()
        if cursor.rowcount != 1:
            raise ValueError(f"Hermes job not found: {job_id}")


def set_hermes_job_progress(db_path: Path, job_id: str, progress_summary: str) -> None:
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "UPDATE hermes_jobs SET progress_summary = ? WHERE id = ?",
            (progress_summary, job_id),
        )
        conn.commit()
        if cursor.rowcount != 1:
            raise ValueError(f"Hermes job not found: {job_id}")


def complete_hermes_job(db_path: Path, job_id: str, *, final_result: str) -> None:
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE hermes_jobs
            SET status = 'completed', final_result = ?, finished_at = ?, status_note = NULL
            WHERE id = ? AND status IN ('running', 'cancel_pending')
            """,
            (final_result, _utc_now_iso(), job_id),
        )
        conn.commit()
        if cursor.rowcount != 1:
            raise ValueError(f"Hermes job not found or not active: {job_id}")


def fail_hermes_job(db_path: Path, job_id: str, *, status_note: str) -> None:
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE hermes_jobs
            SET status = 'failed', status_note = ?, finished_at = ?
            WHERE id = ? AND status IN ('running', 'cancel_pending')
            """,
            (status_note, _utc_now_iso(), job_id),
        )
        conn.commit()
        if cursor.rowcount != 1:
            raise ValueError(f"Hermes job not found or not active: {job_id}")


def request_hermes_job_cancel(db_path: Path, job_id: str) -> None:
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE hermes_jobs
            SET status = 'cancel_pending'
            WHERE id = ? AND status = 'running'
            """,
            (job_id,),
        )
        conn.commit()
        if cursor.rowcount != 1:
            raise ValueError(f"Hermes job not found or not running: {job_id}")


def cancel_hermes_job(
    db_path: Path,
    job_id: str,
    *,
    status_note: str = "cancelled by caller",
) -> None:
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE hermes_jobs
            SET status = 'cancelled', status_note = ?, finished_at = ?
            WHERE id = ? AND status IN ('running', 'cancel_pending')
            """,
            (status_note, _utc_now_iso(), job_id),
        )
        conn.commit()
        if cursor.rowcount != 1:
            raise ValueError(f"Hermes job not found or not active: {job_id}")


def mark_stale_running_jobs_orphaned(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE hermes_jobs
            SET status = 'failed_orphaned', status_note = ?, finished_at = ?
            WHERE status IN ('running', 'cancel_pending')
            """,
            (ORPHANED_STATUS_NOTE, _utc_now_iso()),
        )
        conn.commit()
        return cursor.rowcount
