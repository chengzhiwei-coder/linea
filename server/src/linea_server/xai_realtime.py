from typing import Any

from linea_server.xai_config import XaiConfig


TIME_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "name": "get_current_time",
    "description": "Return the server local time as an ISO-8601 timestamp.",
    "parameters": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}


def build_session_update(config: XaiConfig) -> dict[str, Any]:
    return {
        "type": "session.update",
        "session": {
            "model": config.model,
            "voice": config.voice,
            "instructions": "You are Linea, Anton's concise realtime voice assistant.",
            "turn_detection": {"type": "server_vad"},
            "tools": [TIME_TOOL_SCHEMA],
        },
    }


class XaiRealtimeClient:
    """Thin boundary around xAI's realtime WebSocket API.

    The real connect/send/receive loop lands later after WebRTC frame plumbing exists.
    Keep this class small and easy to fake in tests.
    """

    def __init__(self, config: XaiConfig) -> None:
        self.config = config

    def authorization_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.api_key}"}
