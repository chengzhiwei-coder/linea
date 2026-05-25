import asyncio
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from linea_server.hermes_jobs import (
    cancel_hermes_job,
    complete_hermes_job,
    create_hermes_job,
    fail_hermes_job,
    get_active_hermes_job,
    get_latest_hermes_job,
    mark_stale_running_jobs_orphaned,
    request_hermes_job_cancel,
    set_hermes_job_pid,
)

DEFAULT_PROFILE = "default"
DEFAULT_HERMES_LOG_ROOT = Path(".data/hermes_jobs")
_MAX_FINAL_RESULT_BYTES = 64 * 1024
_RUNNING_PROGRESS_FALLBACK = "Hermes is still running; no detailed progress signal is available yet."
_COMPLETED_STATUS_MESSAGE = "The latest Hermes job completed; the final result will be sent to Telegram."
_FAILED_STATUS_MESSAGE = "The latest Hermes job failed; check local diagnostics if needed."
_CANCELLED_STATUS_MESSAGE = "The latest Hermes job was cancelled."
_SECRET_PATTERNS = (
    re.compile(r"Bearer\s+\S+", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
)
_UNSAFE_PROGRESS_MARKERS = ("Traceback (most recent call last):",)


def resolve_profile_home(profile: str | None = None, *, os_home: Path | None = None) -> Path:
    home = Path.home() if os_home is None else os_home
    profile_name = DEFAULT_PROFILE if profile is None else profile
    if profile_name == DEFAULT_PROFILE:
        return home
    return home / ".hermes" / "profiles" / profile_name / "home"


def build_hermes_prompt(task: str) -> str:
    return (
        f"{task}\n\n"
        "When you are done, send the final result to the Telegram home channel. "
        "Keep the delivered result concise and useful."
    )


def build_hermes_argv(prompt: str) -> list[str]:
    return ["hermes", "chat", "-Q", "-q", prompt]


def extract_safe_progress_summary(text: str, *, max_chars: int = 4000) -> str | None:
    """Return a capped, redacted one-sentence progress summary or None if unsafe."""
    if len(text) > max_chars:
        return None
    recent_text = text[-max_chars:]
    if any(marker in recent_text for marker in _UNSAFE_PROGRESS_MARKERS):
        return None
    redacted = recent_text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[redacted]", redacted)
    normalized = " ".join(redacted.split()).strip()
    if not normalized:
        return None
    if len(normalized) > 160:
        normalized = normalized[:159].rstrip() + "…"
    return normalized


def _lifecycle_status_message(status: str) -> str:
    if status in {"running", "cancel_pending"}:
        return _RUNNING_PROGRESS_FALLBACK
    if status == "idle":
        return "No Hermes jobs yet."
    if status == "completed":
        return _COMPLETED_STATUS_MESSAGE
    if status in {"failed", "failed_orphaned"}:
        return _FAILED_STATUS_MESSAGE
    if status == "cancelled":
        return _CANCELLED_STATUS_MESSAGE
    return f"Hermes job is {status}"


def _read_final_stdout(stdout_path: Path) -> str:
    if not stdout_path.exists() or stdout_path.stat().st_size == 0:
        return f"Hermes exited successfully; see stdout log: {stdout_path}"

    with stdout_path.open("rb") as stdout_file:
        size = stdout_path.stat().st_size
        if size > _MAX_FINAL_RESULT_BYTES:
            stdout_file.seek(-_MAX_FINAL_RESULT_BYTES, 2)
        output = stdout_file.read().decode(errors="replace").strip()
    return output or f"Hermes exited successfully; see stdout log: {stdout_path}"


class HermesJobManager:
    def __init__(
        self,
        *,
        db_path: Path,
        log_root: Path = DEFAULT_HERMES_LOG_ROOT,
        profile: str | None = None,
        create_subprocess_exec: Callable[..., Awaitable[asyncio.subprocess.Process]] = asyncio.create_subprocess_exec,
    ) -> None:
        self._db_path = db_path
        self._log_root = log_root
        self._profile = DEFAULT_PROFILE if profile is None else profile
        self._profile_home = resolve_profile_home(profile)
        self._create_subprocess_exec = create_subprocess_exec
        self._lock = asyncio.Lock()
        self._active_process: asyncio.subprocess.Process | None = None
        self._active_job_id: str | None = None
        self._watch_task: asyncio.Task[None] | None = None
        self._cancelling_job_ids: set[str] = set()
        mark_stale_running_jobs_orphaned(self._db_path)

    async def start_task(self, task: str) -> dict[str, Any]:
        async with self._lock:
            active = get_active_hermes_job(self._db_path)
            if active is not None:
                return {
                    "ok": False,
                    "status": "busy",
                    "job_id": active.id,
                    "message": "A Hermes job is already running",
                }

            prompt = build_hermes_prompt(task)
            job_id = str(uuid4())
            job_log_dir = self._log_root / job_id
            job_log_dir.mkdir(parents=True, exist_ok=True)
            stdout_path = job_log_dir / "stdout.log"
            stderr_path = job_log_dir / "stderr.log"
            stdout_path.touch()
            stderr_path.touch()

            try:
                job = create_hermes_job(
                    self._db_path,
                    task=task,
                    prompt=prompt,
                    profile=self._profile,
                    profile_home=self._profile_home,
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    job_id=job_id,
                )
            except ValueError:
                active = get_active_hermes_job(self._db_path)
                if active is None:
                    raise
                return {
                    "ok": False,
                    "status": "busy",
                    "job_id": active.id,
                    "message": "A Hermes job is already running",
                }

            stdout_file = stdout_path.open("ab")
            stderr_file = stderr_path.open("ab")
            process: asyncio.subprocess.Process | None = None
            try:
                process = await self._create_subprocess_exec(
                    *build_hermes_argv(prompt),
                    stdout=stdout_file,
                    stderr=stderr_file,
                    cwd=self._profile_home,
                )
                set_hermes_job_pid(self._db_path, job.id, process.pid)
            except BaseException as exc:
                stdout_file.close()
                stderr_file.close()
                if process is not None and process.returncode is None:
                    process.terminate()
                try:
                    fail_hermes_job(self._db_path, job.id, status_note=f"failed to launch Hermes: {exc}")
                except Exception:
                    pass
                raise

            assert process is not None
            self._active_process = process
            self._active_job_id = job.id
            self._watch_task = asyncio.create_task(
                self._watch_process(
                    process=process,
                    job_id=job.id,
                    stdout_path=stdout_path,
                    stdout_file=stdout_file,
                    stderr_file=stderr_file,
                )
            )
            self._watch_task.add_done_callback(self._discard_watch_task_exception)
            return {
                "ok": True,
                "status": "running",
                "job_id": job.id,
                "message": "Hermes job started",
            }

    async def get_status(self) -> dict[str, Any]:
        active = get_active_hermes_job(self._db_path)
        if active is not None:
            safe_progress_summary = extract_safe_progress_summary(active.progress_summary) if active.progress_summary else None
            return {
                "ok": True,
                "status": active.status,
                "job_id": active.id,
                "progress_summary": safe_progress_summary,
                "message": safe_progress_summary or _RUNNING_PROGRESS_FALLBACK,
            }
        latest = get_latest_hermes_job(self._db_path)
        if latest is None:
            return {"ok": True, "status": "idle", "job_id": None, "message": _lifecycle_status_message("idle")}
        return {
            "ok": True,
            "status": latest.status,
            "job_id": latest.id,
            "message": _lifecycle_status_message(latest.status),
        }

    async def request_cancel(self) -> dict[str, Any]:
        async with self._lock:
            active = get_active_hermes_job(self._db_path)
            if active is None:
                return {"ok": False, "status": "idle", "job_id": None, "message": "No active Hermes job"}
            if active.status == "running":
                request_hermes_job_cancel(self._db_path, active.id)
            return {
                "ok": True,
                "status": "cancel_pending",
                "job_id": active.id,
                "message": "Cancel requested; confirm to terminate the Hermes job",
            }

    async def confirm_cancel(self) -> dict[str, Any]:
        async with self._lock:
            active = get_active_hermes_job(self._db_path)
            if active is None:
                return {"ok": False, "status": "idle", "job_id": None, "message": "No active Hermes job"}
            self._cancelling_job_ids.add(active.id)
            process = self._active_process if self._active_job_id == active.id else None
            if process is not None and process.returncode is None:
                process.terminate()
            return {
                "ok": True,
                "status": "cancel_pending",
                "job_id": active.id,
                "message": "Hermes job termination requested",
            }

    @staticmethod
    def _discard_watch_task_exception(task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        task.exception()

    async def _watch_process(
        self,
        *,
        process: asyncio.subprocess.Process,
        job_id: str,
        stdout_path: Path,
        stdout_file: Any,
        stderr_file: Any,
    ) -> None:
        try:
            returncode = await process.wait()
        finally:
            stdout_file.close()
            stderr_file.close()

        try:
            if job_id in self._cancelling_job_ids:
                cancel_hermes_job(self._db_path, job_id)
            elif returncode == 0:
                complete_hermes_job(self._db_path, job_id, final_result=_read_final_stdout(stdout_path))
            else:
                fail_hermes_job(self._db_path, job_id, status_note=f"Hermes exited with code {returncode}")
        finally:
            async with self._lock:
                if self._active_job_id == job_id:
                    self._active_job_id = None
                    self._active_process = None
                self._cancelling_job_ids.discard(job_id)
