import pytest


@pytest.fixture(autouse=True)
def configured_xai_api_key(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key")
