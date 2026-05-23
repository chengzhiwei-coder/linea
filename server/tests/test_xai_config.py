import pytest

from linea_server.xai_config import XaiConfig, load_xai_config


def test_load_xai_config_requires_api_key(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="XAI_API_KEY"):
        load_xai_config()


def test_load_xai_config_uses_safe_defaults(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    monkeypatch.delenv("XAI_REALTIME_URL", raising=False)
    monkeypatch.delenv("XAI_REALTIME_MODEL", raising=False)
    monkeypatch.delenv("XAI_REALTIME_VOICE", raising=False)

    config = load_xai_config()

    assert config == XaiConfig(
        api_key="test-key",
        realtime_url="wss://api.x.ai/v1/realtime",
        model="grok-voice-think-fast-1.0",
        voice="eve",
    )
