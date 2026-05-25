import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from linea_server.db import initialize_db
from linea_server.hermes_jobs import create_hermes_job, get_active_hermes_job, get_latest_hermes_job
from linea_server.hermes_runner import (
    HermesJobManager,
    build_hermes_argv,
    build_hermes_prompt,
    resolve_profile_home,
)


class FakeProcess:
    def __init__(self, *, pid: int = 123, returncode: int = 0) -> None:
        self.pid = pid
        self.returncode: int | None = None
        self._final_returncode = returncode
        self._done = asyncio.Event()
        self.wait_calls = 0
        self.terminate_calls = 0
        self.kill_calls = 0

    async def wait(self) -> int:
        self.wait_calls += 1
        await self._done.wait()
        self.returncode = self._final_returncode
        return self._final_returncode

    def finish(self, returncode: int | None = None) -> None:
        if returncode is not None:
            self._final_returncode = returncode
        self._done.set()

    def terminate(self) -> None:
        self.terminate_calls += 1
        self.finish(-15)

    def kill(self) -> None:
        self.kill_calls += 1
        self.finish(-9)


class FakeSubprocessFactory:
    def __init__(self, process: FakeProcess, *, stdout_bytes: bytes = b"") -> None:
        self.process = process
        self.stdout_bytes = stdout_bytes
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, *argv: str, **kwargs: Any) -> FakeProcess:
        self.calls.append({"argv": list(argv), "kwargs": kwargs})
        if self.stdout_bytes:
            kwargs["stdout"].write(self.stdout_bytes)
            kwargs["stdout"].flush()
        return self.process


@pytest.fixture
def initialized_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "linea.db"
    initialize_db(db_path)
    return db_path


def make_manager(
    db_path: Path,
    tmp_path: Path,
    factory: Callable[..., Awaitable[FakeProcess]],
) -> HermesJobManager:
    return HermesJobManager(
        db_path=db_path,
        log_root=tmp_path / ".data" / "hermes_jobs",
        profile="programmer",
        create_subprocess_exec=factory,
    )


def test_resolve_profile_home_returns_os_home_for_default_profile(tmp_path):
    assert resolve_profile_home(None, os_home=tmp_path) == tmp_path
    assert resolve_profile_home("default", os_home=tmp_path) == tmp_path


def test_resolve_profile_home_returns_named_profile_home_under_hermes_profiles(tmp_path):
    assert (
        resolve_profile_home("programmer", os_home=tmp_path)
        == tmp_path / ".hermes" / "profiles" / "programmer" / "home"
    )


def test_build_hermes_prompt_contains_task_delivery_instruction_and_concision_guidance():
    prompt = build_hermes_prompt("Do X")

    assert "Do X" in prompt
    assert "send the final result to the Telegram home channel" in prompt
    assert "Keep the delivered result concise and useful." in prompt


def test_build_hermes_prompt_does_not_inject_linea_or_server_paths():
    prompt = build_hermes_prompt("Do X")

    assert "/home/singleton/linea" not in prompt
    assert "server/src" not in prompt


def test_build_hermes_prompt_preserves_linea_or_server_paths_from_caller_task():
    task = "Inspect /home/singleton/linea and server/src when explicitly requested."

    prompt = build_hermes_prompt(task)

    assert "/home/singleton/linea" in prompt
    assert "server/src" in prompt


def test_build_hermes_argv_passes_prompt_as_argv_argument():
    prompt = build_hermes_prompt("Do X")

    assert build_hermes_argv(prompt) == ["hermes", "chat", "-Q", "-q", prompt]


async def test_start_task_creates_job_logs_and_returns_ack(initialized_db, tmp_path):
    process = FakeProcess()
    factory = FakeSubprocessFactory(process)
    manager = make_manager(initialized_db, tmp_path, factory)

    ack = await manager.start_task("do work")

    assert ack["ok"] is True
    assert ack["status"] == "running"
    assert isinstance(ack["job_id"], str)
    assert ack["message"] == "Hermes job started"

    job = get_latest_hermes_job(initialized_db)
    assert job is not None
    assert job.id == ack["job_id"]
    assert job.status == "running"
    assert job.task == "do work"
    assert Path(job.stdout_path) == tmp_path / ".data" / "hermes_jobs" / job.id / "stdout.log"
    assert Path(job.stderr_path) == tmp_path / ".data" / "hermes_jobs" / job.id / "stderr.log"
    assert Path(job.stdout_path).is_file()
    assert Path(job.stderr_path).is_file()

    process.finish()
    await asyncio.sleep(0)


async def test_start_task_reports_busy_without_spawning_when_job_active(initialized_db, tmp_path):
    process = FakeProcess()
    factory = FakeSubprocessFactory(process)
    manager = make_manager(initialized_db, tmp_path, factory)

    first = await manager.start_task("first")
    second = await manager.start_task("second")

    assert first["ok"] is True
    assert second == {
        "ok": False,
        "status": "busy",
        "job_id": first["job_id"],
        "message": "A Hermes job is already running",
    }
    assert len(factory.calls) == 1

    process.finish()
    await asyncio.sleep(0)


async def test_start_task_uses_resolved_profile_home_and_argv_without_shell(initialized_db, tmp_path):
    process = FakeProcess()
    factory = FakeSubprocessFactory(process)
    manager = make_manager(initialized_db, tmp_path, factory)

    ack = await manager.start_task("do work")

    prompt = build_hermes_prompt("do work")
    assert factory.calls[0]["argv"] == ["hermes", "chat", "-Q", "-q", prompt]
    assert factory.calls[0]["kwargs"]["cwd"] == resolve_profile_home("programmer")
    assert "shell" not in factory.calls[0]["kwargs"]
    assert ack["job_id"]

    process.finish()
    await asyncio.sleep(0)


async def test_watch_process_awaits_process_without_linea_timeout(monkeypatch, initialized_db, tmp_path):
    def fail_if_used(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Hermes job manager must not impose an asyncio.wait_for timeout")

    import linea_server.hermes_runner as hermes_runner

    monkeypatch.setattr(hermes_runner.asyncio, "wait_for", fail_if_used)
    process = FakeProcess()
    factory = FakeSubprocessFactory(process)
    manager = make_manager(initialized_db, tmp_path, factory)

    await manager.start_task("do work")
    process.finish()
    await asyncio.sleep(0)

    assert process.wait_calls == 1
    assert get_active_hermes_job(initialized_db) is None


async def test_successful_exit_stores_stdout_as_final_result(initialized_db, tmp_path):
    process = FakeProcess(returncode=0)
    factory = FakeSubprocessFactory(process, stdout_bytes=b"Final answer from Hermes\n")
    manager = make_manager(initialized_db, tmp_path, factory)

    ack = await manager.start_task("do work")
    process.finish(0)
    await asyncio.sleep(0)

    job = get_latest_hermes_job(initialized_db)
    assert job is not None
    assert job.id == ack["job_id"]
    assert job.status == "completed"
    assert job.final_result == "Final answer from Hermes"


async def test_non_zero_exit_marks_job_failed_with_compact_note(initialized_db, tmp_path):
    process = FakeProcess(returncode=2)
    factory = FakeSubprocessFactory(process)
    manager = make_manager(initialized_db, tmp_path, factory)

    ack = await manager.start_task("do work")
    process.finish(2)
    await asyncio.sleep(0)

    job = get_latest_hermes_job(initialized_db)
    assert job is not None
    assert job.id == ack["job_id"]
    assert job.status == "failed"
    assert job.status_note == "Hermes exited with code 2"


async def test_manager_startup_marks_stale_running_jobs_orphaned(initialized_db, tmp_path):
    stale = create_hermes_job(
        initialized_db,
        task="stale",
        prompt="stale prompt",
        profile="programmer",
        profile_home=tmp_path / "profile-home",
        stdout_path=tmp_path / "old" / "stdout.log",
        stderr_path=tmp_path / "old" / "stderr.log",
    )
    process = FakeProcess()
    factory = FakeSubprocessFactory(process)

    make_manager(initialized_db, tmp_path, factory)

    assert get_active_hermes_job(initialized_db) is None
    job = get_latest_hermes_job(initialized_db)
    assert job is not None
    assert job.id == stale.id
    assert job.status == "failed_orphaned"
