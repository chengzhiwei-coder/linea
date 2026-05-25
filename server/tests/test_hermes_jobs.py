import sqlite3

import pytest

from linea_server.db import initialize_db
from linea_server.hermes_jobs import (
    cancel_hermes_job,
    complete_hermes_job,
    create_hermes_job,
    fail_hermes_job,
    get_active_hermes_job,
    get_latest_hermes_job,
    mark_stale_running_jobs_orphaned,
    request_hermes_job_cancel,
)


def test_create_hermes_job_inserts_running_row_with_log_paths_and_prompt(tmp_path):
    db_path = tmp_path / "linea.db"
    initialize_db(db_path)

    job = create_hermes_job(
        db_path,
        task="Summarize status",
        prompt="Tell Anton what happened",
        profile="programmer",
        profile_home=tmp_path / "profile-home",
        stdout_path=tmp_path / "jobs" / "job-1" / "stdout.log",
        stderr_path=tmp_path / "jobs" / "job-1" / "stderr.log",
    )

    assert job.status == "running"
    assert job.task == "Summarize status"
    assert job.prompt == "Tell Anton what happened"
    assert job.profile == "programmer"
    assert job.profile_home == str(tmp_path / "profile-home")
    assert job.stdout_path == str(tmp_path / "jobs" / "job-1" / "stdout.log")
    assert job.stderr_path == str(tmp_path / "jobs" / "job-1" / "stderr.log")
    assert job.delivery_status == "requested"
    assert job.final_result is None
    assert job.finished_at is None

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT id, status, task, prompt, profile, profile_home, stdout_path, stderr_path
            FROM hermes_jobs
            """
        ).fetchone()

    assert row == (
        job.id,
        "running",
        "Summarize status",
        "Tell Anton what happened",
        "programmer",
        str(tmp_path / "profile-home"),
        str(tmp_path / "jobs" / "job-1" / "stdout.log"),
        str(tmp_path / "jobs" / "job-1" / "stderr.log"),
    )


def test_get_active_hermes_job_returns_only_running_or_cancel_pending_jobs(tmp_path):
    db_path = tmp_path / "linea.db"
    initialize_db(db_path)

    completed = create_hermes_job(
        db_path,
        task="Old task",
        prompt="Old prompt",
        profile="programmer",
        profile_home=tmp_path / "profile-home",
        stdout_path=tmp_path / "old" / "stdout.log",
        stderr_path=tmp_path / "old" / "stderr.log",
    )
    complete_hermes_job(db_path, completed.id, final_result="done")
    assert get_active_hermes_job(db_path) is None

    running = create_hermes_job(
        db_path,
        task="Current task",
        prompt="Current prompt",
        profile="programmer",
        profile_home=tmp_path / "profile-home",
        stdout_path=tmp_path / "current" / "stdout.log",
        stderr_path=tmp_path / "current" / "stderr.log",
    )
    assert get_active_hermes_job(db_path) == running

    request_hermes_job_cancel(db_path, running.id)
    active = get_active_hermes_job(db_path)
    assert active is not None
    assert active.id == running.id
    assert active.status == "cancel_pending"


def test_create_hermes_job_rejects_existing_active_job(tmp_path):
    db_path = tmp_path / "linea.db"
    initialize_db(db_path)
    create_hermes_job(
        db_path,
        task="Current task",
        prompt="Current prompt",
        profile="programmer",
        profile_home=tmp_path / "profile-home",
        stdout_path=tmp_path / "current" / "stdout.log",
        stderr_path=tmp_path / "current" / "stderr.log",
    )

    with pytest.raises(ValueError, match="active Hermes job already exists"):
        create_hermes_job(
            db_path,
            task="Other task",
            prompt="Other prompt",
            profile="programmer",
            profile_home=tmp_path / "profile-home",
            stdout_path=tmp_path / "other" / "stdout.log",
            stderr_path=tmp_path / "other" / "stderr.log",
        )


def test_complete_hermes_job_stores_final_result_completed_and_finished_at(tmp_path):
    db_path = tmp_path / "linea.db"
    initialize_db(db_path)
    job = create_hermes_job(
        db_path,
        task="Task",
        prompt="Prompt",
        profile="programmer",
        profile_home=tmp_path / "profile-home",
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
    )

    complete_hermes_job(db_path, job.id, final_result="Final answer")

    latest = get_latest_hermes_job(db_path)
    assert latest is not None
    assert latest.id == job.id
    assert latest.status == "completed"
    assert latest.final_result == "Final answer"
    assert latest.finished_at is not None


def test_complete_hermes_job_rejects_already_finished_job(tmp_path):
    db_path = tmp_path / "linea.db"
    initialize_db(db_path)
    job = create_hermes_job(
        db_path,
        task="Task",
        prompt="Prompt",
        profile="programmer",
        profile_home=tmp_path / "profile-home",
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
    )
    cancel_hermes_job(db_path, job.id)

    with pytest.raises(ValueError, match="not active"):
        complete_hermes_job(db_path, job.id, final_result="too late")


def test_fail_hermes_job_stores_failed_and_status_note(tmp_path):
    db_path = tmp_path / "linea.db"
    initialize_db(db_path)
    job = create_hermes_job(
        db_path,
        task="Task",
        prompt="Prompt",
        profile="programmer",
        profile_home=tmp_path / "profile-home",
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
    )

    fail_hermes_job(db_path, job.id, status_note="process exited 1")

    latest = get_latest_hermes_job(db_path)
    assert latest is not None
    assert latest.status == "failed"
    assert latest.status_note == "process exited 1"
    assert latest.finished_at is not None


def test_mark_stale_running_jobs_orphaned_frees_active_slot(tmp_path):
    db_path = tmp_path / "linea.db"
    initialize_db(db_path)
    running = create_hermes_job(
        db_path,
        task="Running",
        prompt="Prompt",
        profile="programmer",
        profile_home=tmp_path / "profile-home",
        stdout_path=tmp_path / "running" / "stdout.log",
        stderr_path=tmp_path / "running" / "stderr.log",
    )
    request_hermes_job_cancel(db_path, running.id)

    changed = mark_stale_running_jobs_orphaned(db_path)

    assert changed == 1
    assert get_active_hermes_job(db_path) is None
    latest = get_latest_hermes_job(db_path)
    assert latest is not None
    assert latest.id == running.id
    assert latest.status == "failed_orphaned"
    assert latest.finished_at is not None
    assert latest.status_note == "server restarted while Hermes job was active"

    next_job = create_hermes_job(
        db_path,
        task="Next",
        prompt="Next prompt",
        profile="programmer",
        profile_home=tmp_path / "profile-home",
        stdout_path=tmp_path / "next" / "stdout.log",
        stderr_path=tmp_path / "next" / "stderr.log",
    )
    assert get_active_hermes_job(db_path) == next_job
