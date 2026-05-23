import pytest

from linea_server.app import create_app
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
