import pytest
import sqlite3

from linea_server.app import create_app
from linea_server.hermes_runner import HermesJobManager
from linea_server.xai_realtime import XaiRealtimeBridge


def test_create_app_requires_xai_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="XAI_API_KEY"):
        create_app(db_path=tmp_path / "linea.db")


def test_create_app_initializes_db_at_given_path(tmp_path, monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    db_path = tmp_path / "linea.db"

    app = create_app(db_path=db_path)

    assert app.state.db_path == db_path
    assert db_path.exists()


def test_create_app_wires_xai_bridge_when_api_key_is_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key")

    app = create_app(db_path=tmp_path / "linea.db")

    assert isinstance(app.state.xai_bridge, XaiRealtimeBridge)
    assert app.state.webrtc_service._audio_sink == app.state.xai_bridge.send_audio_frame
    assert app.state.webrtc_service._audio_source == app.state.xai_bridge.receive_audio_frame


def test_create_app_initializes_hermes_job_manager(tmp_path, monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key")

    app = create_app(db_path=tmp_path / "linea.db")

    assert isinstance(app.state.hermes_job_manager, HermesJobManager)


def test_create_app_orphans_stale_hermes_jobs_on_startup(tmp_path, monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    db_path = tmp_path / "linea.db"
    app = create_app(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO hermes_jobs (
                id, status, task, prompt, profile, profile_home, stdout_path, stderr_path
            )
            VALUES ('stale-job', 'running', 'task', 'prompt', 'default', '/', 'stdout.log', 'stderr.log')
            """
        )
        conn.commit()

    restarted = create_app(db_path=db_path)

    assert isinstance(app.state.hermes_job_manager, HermesJobManager)
    assert isinstance(restarted.state.hermes_job_manager, HermesJobManager)
    with sqlite3.connect(db_path) as conn:
        status = conn.execute("SELECT status FROM hermes_jobs WHERE id = 'stale-job'").fetchone()[0]
    assert status == "failed_orphaned"


def test_create_app_wires_hermes_tool_schemas_into_initial_bridge(tmp_path, monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key")

    app = create_app(db_path=tmp_path / "linea.db")

    tool_names = {schema["name"] for schema in app.state.xai_bridge._tool_registry.tool_schemas()}
    assert {"get_current_time", "run_hermes_task", "get_hermes_status", "cancel_hermes_task"} <= tool_names
