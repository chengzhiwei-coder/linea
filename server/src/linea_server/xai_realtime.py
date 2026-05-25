import asyncio
import base64
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from websockets.asyncio.client import ClientConnection, connect

from linea_server.db import DEFAULT_DB_PATH
from linea_server.tool_logs import finish_tool_call, start_tool_call
from linea_server.tools import DEFAULT_TIME_TOOL_SCHEMA, ToolRegistry, register_default_tools
from linea_server.xai_config import XaiConfig

logger = logging.getLogger(__name__)

XAI_AUDIO_SAMPLE_RATE = 48_000


TIME_TOOL_SCHEMA = DEFAULT_TIME_TOOL_SCHEMA


class XaiRealtimeError(RuntimeError):
    """Raised when xAI realtime reports a fatal provider error."""


def build_session_update(config: XaiConfig, tool_schemas: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "type": "session.update",
        "session": {
            "model": config.model,
            "voice": config.voice,
            "instructions": "You are Linea, Anton's concise realtime voice assistant.",
            "turn_detection": {"type": "server_vad"},
            "audio": {
                "input": {"format": {"type": "audio/pcm", "rate": XAI_AUDIO_SAMPLE_RATE}},
                "output": {"format": {"type": "audio/pcm", "rate": XAI_AUDIO_SAMPLE_RATE}},
            },
            "tools": tool_schemas or [TIME_TOOL_SCHEMA],
        },
    }


def build_initial_greeting_events(greeting_text: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": f"The WebRTC call just connected. Say exactly: {greeting_text}",
                    }
                ],
            },
        },
        {"type": "response.create"},
    ]


class XaiRealtimeClient:
    """Thin boundary around xAI's realtime WebSocket API."""

    def __init__(self, config: XaiConfig) -> None:
        self.config = config

    def authorization_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.api_key}"}


class RealtimeConnection(Protocol):
    async def send_json(self, payload: dict[str, Any]) -> None:
        """Send one JSON event to the realtime provider."""
        ...

    def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        """Yield decoded JSON events from the realtime provider."""
        ...

    async def close(self) -> None:
        """Close the underlying provider transport."""
        ...


class WebSocketRealtimeConnection:
    """JSON event adapter around the xAI realtime WebSocket connection."""

    def __init__(self, websocket: ClientConnection) -> None:
        self._websocket = websocket

    async def send_json(self, payload: dict[str, Any]) -> None:
        await self._websocket.send(json.dumps(payload))

    async def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        async for message in self._websocket:
            if isinstance(message, bytes):
                message = message.decode("utf-8")
            yield json.loads(message)

    async def close(self) -> None:
        await self._websocket.close()


ActivityRecorder = Callable[[], None]
ConnectionFactory = Callable[[XaiConfig], Awaitable[RealtimeConnection]]
ToolCallActivePredicate = Callable[[str], bool]
InputSpeechStartedCallback = Callable[[], None]


@dataclass(frozen=True)
class XaiToolCallRequest:
    call_id: str
    name: str
    arguments: dict[str, Any]


async def connect_xai_realtime(config: XaiConfig) -> RealtimeConnection:
    try:
        websocket = await connect(
            config.realtime_url,
            additional_headers=XaiRealtimeClient(config).authorization_header(),
        )
    except Exception:
        logger.exception("xAI realtime connect/auth failure url=%s model=%s", config.realtime_url, config.model)
        raise
    return WebSocketRealtimeConnection(websocket)


def parse_tool_call_event(event: dict[str, Any]) -> XaiToolCallRequest | None:
    if event.get("type") != "response.function_call_arguments.done":
        return None

    name = event.get("name")
    call_id = event.get("call_id")
    if not isinstance(name, str) or not isinstance(call_id, str):
        return None
    return XaiToolCallRequest(call_id=call_id, name=name, arguments=_parse_tool_arguments(event.get("arguments")))


def _parse_tool_arguments(arguments: Any) -> dict[str, Any]:
    if arguments is None or arguments == "":
        return {}
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        parsed = json.loads(arguments)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("invalid tool arguments")


class XaiRealtimeBridge:
    """Bridge PCM16 audio frames between WebRTC plumbing and xAI realtime events.

    The WebRTC layer owns capture/playback. This class owns the xAI session lifecycle and the
    provider event names: PCM16 bytes are sent as input_audio_buffer.append events, and xAI
    response.output_audio.delta events are decoded into PCM16 bytes for the WebRTC output side.
    """

    def __init__(
        self,
        config: XaiConfig,
        *,
        connection: RealtimeConnection | None = None,
        connection_factory: ConnectionFactory = connect_xai_realtime,
        db_path: Path = DEFAULT_DB_PATH,
        tool_registry: ToolRegistry | None = None,
        is_tool_call_active: ToolCallActivePredicate = lambda call_id: False,
        record_activity: ActivityRecorder | None = None,
        initial_greeting_text: str | None = None,
        on_input_speech_started: InputSpeechStartedCallback | None = None,
    ) -> None:
        self._config = config
        self._connection = connection
        self._connection_factory = connection_factory
        self._db_path = db_path
        self._tool_registry = tool_registry or ToolRegistry()
        if tool_registry is None:
            register_default_tools(self._tool_registry)
        self._is_tool_call_active = is_tool_call_active
        self._record_activity = record_activity
        self._initial_greeting_text = initial_greeting_text
        self._on_input_speech_started = on_input_speech_started
        self._suppress_input_until_greeting_done = initial_greeting_text is not None
        self._start_lock = asyncio.Lock()
        self._started = False
        self._closed = False
        self._audio_output: asyncio.Queue[bytes] = asyncio.Queue()

    async def start(self) -> None:
        async with self._start_lock:
            if self._closed:
                raise RuntimeError("xAI realtime bridge is closed")
            if self._started:
                return
            if self._connection is None:
                self._connection = await self._connection_factory(self._config)
            await self._connection.send_json(build_session_update(self._config, self._tool_registry.tool_schemas()))
            self._record_call_activity()
            if self._initial_greeting_text is not None:
                for event in build_initial_greeting_events(self._initial_greeting_text):
                    await self._connection.send_json(event)
                    self._record_call_activity()
            self._started = True

    async def send_audio_frame(self, pcm16: bytes) -> None:
        await self.start()
        if self._suppress_input_until_greeting_done:
            return
        assert self._connection is not None
        await self._connection.send_json(
            {
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(pcm16).decode("ascii"),
            }
        )
        self._record_call_activity()

    async def process_events(self) -> None:
        await self.start()
        assert self._connection is not None
        async for event in self._connection:
            self._record_call_activity()
            event_type = event.get("type")
            if event_type in {"response.output_audio.delta", "response.audio.delta"}:
                encoded_audio = event.get("delta")
                if isinstance(encoded_audio, str):
                    await self._audio_output.put(base64.b64decode(encoded_audio))
            elif event_type in {"response.output_audio.done", "response.audio.done", "response.done"}:
                self._suppress_input_until_greeting_done = False
            elif event_type == "input_audio_buffer.speech_started":
                self._suppress_input_until_greeting_done = False
                self._clear_audio_output()
                if self._on_input_speech_started is not None:
                    self._on_input_speech_started()
            elif event_type == "error":
                logger.error("xAI realtime provider error")
                await self.close()
                raise XaiRealtimeError(str(event.get("error") or event))
            elif event_type == "response.function_call_arguments.done":
                try:
                    tool_call = parse_tool_call_event(event)
                except ValueError:
                    await self._handle_invalid_tool_arguments(event)
                    continue
                if tool_call is not None:
                    await self._handle_tool_call(tool_call)

    def _record_call_activity(self) -> None:
        if self._record_activity is not None:
            self._record_activity()

    async def _handle_tool_call(self, tool_call: XaiToolCallRequest) -> None:
        assert self._connection is not None
        tool_call_id = start_tool_call(self._db_path, tool_call.call_id, tool_call.name)
        try:
            result = await self._tool_registry.call(tool_call.name, tool_call.arguments)
        except asyncio.CancelledError:
            finish_tool_call(self._db_path, tool_call_id, "cancelled")
            raise
        except Exception:
            finish_tool_call(self._db_path, tool_call_id, "error")
            return

        finish_tool_call(self._db_path, tool_call_id, "success")
        if not self._is_tool_call_active(tool_call.call_id):
            return

        await self._send_tool_output(tool_call.call_id, result)

    async def _handle_invalid_tool_arguments(self, event: dict[str, Any]) -> None:
        name = event.get("name")
        call_id = event.get("call_id")
        if not isinstance(name, str) or not isinstance(call_id, str):
            return
        tool_call_id = start_tool_call(self._db_path, call_id, name)
        finish_tool_call(self._db_path, tool_call_id, "error")
        if self._is_tool_call_active(call_id):
            await self._send_tool_output(call_id, json.dumps({"ok": False, "error": "invalid tool arguments"}))

    async def _send_tool_output(self, call_id: str, output: str) -> None:
        assert self._connection is not None
        await self._connection.send_json(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": output,
                },
            }
        )
        self._record_call_activity()
        await self._connection.send_json({"type": "response.create"})
        self._record_call_activity()

    async def receive_audio_frame(self) -> bytes | None:
        try:
            return self._audio_output.get_nowait()
        except asyncio.QueueEmpty:
            return None

    def _clear_audio_output(self) -> None:
        while True:
            try:
                self._audio_output.get_nowait()
            except asyncio.QueueEmpty:
                return

    async def close(self) -> None:
        self._closed = True
        self._started = False
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
