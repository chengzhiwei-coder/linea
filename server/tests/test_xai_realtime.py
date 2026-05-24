import base64

import pytest

from linea_server.xai_config import XaiConfig
from linea_server.xai_realtime import (
    XAI_AUDIO_SAMPLE_RATE,
    XaiRealtimeBridge,
    XaiRealtimeError,
    build_session_update,
)


class FakeRealtimeConnection:
    def __init__(self, incoming_events):
        self.incoming_events = list(incoming_events)
        self.sent = []
        self.closed = False

    async def send_json(self, payload):
        self.sent.append(payload)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.incoming_events:
            raise StopAsyncIteration
        return self.incoming_events.pop(0)

    async def close(self):
        self.closed = True


async def test_bridge_sends_session_update_and_pcm_audio_to_xai():
    connection = FakeRealtimeConnection([])
    bridge = XaiRealtimeBridge(
        XaiConfig(api_key="secret", realtime_url="wss://api.x.ai/v1/realtime"),
        connection=connection,
    )

    await bridge.start()
    await bridge.send_audio_frame(b"\x01\x02")

    assert connection.sent[0]["type"] == "session.update"
    assert connection.sent[1] == {
        "type": "input_audio_buffer.append",
        "audio": base64.b64encode(b"\x01\x02").decode("ascii"),
    }


async def test_bridge_can_request_initial_greeting_after_session_start():
    connection = FakeRealtimeConnection([])
    bridge = XaiRealtimeBridge(
        XaiConfig(api_key="secret", realtime_url="wss://api.x.ai/v1/realtime"),
        connection=connection,
        initial_greeting_text="Hey, how can I help you?",
    )

    await bridge.start()

    assert connection.sent[0]["type"] == "session.update"
    assert connection.sent[1] == {
        "type": "conversation.item.create",
        "item": {
            "type": "message",
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": "The WebRTC call just connected. Say exactly: Hey, how can I help you?",
                }
            ],
        },
    }
    assert connection.sent[2] == {"type": "response.create"}


async def test_initial_greeting_suppresses_microphone_echo_until_response_done():
    connection = FakeRealtimeConnection([])
    bridge = XaiRealtimeBridge(
        XaiConfig(api_key="secret", realtime_url="wss://api.x.ai/v1/realtime"),
        connection=connection,
        initial_greeting_text="Hey, how can I help you?",
    )

    await bridge.send_audio_frame(b"\x01\x02")

    assert [event["type"] for event in connection.sent] == [
        "session.update",
        "conversation.item.create",
        "response.create",
    ]


async def test_initial_greeting_allows_microphone_after_response_done():
    connection = FakeRealtimeConnection([{"type": "response.done"}])
    bridge = XaiRealtimeBridge(
        XaiConfig(api_key="secret", realtime_url="wss://api.x.ai/v1/realtime"),
        connection=connection,
        initial_greeting_text="Hey, how can I help you?",
    )

    await bridge.process_events()
    await bridge.send_audio_frame(b"\x01\x02")

    assert connection.sent[-1] == {
        "type": "input_audio_buffer.append",
        "audio": base64.b64encode(b"\x01\x02").decode("ascii"),
    }


async def test_bridge_receives_xai_audio_delta_for_webrtc_output():
    pcm = b"\x03\x04"
    connection = FakeRealtimeConnection(
        [
            {
                "type": "response.output_audio.delta",
                "delta": base64.b64encode(pcm).decode("ascii"),
            }
        ]
    )
    bridge = XaiRealtimeBridge(
        XaiConfig(api_key="secret", realtime_url="wss://api.x.ai/v1/realtime"),
        connection=connection,
    )

    await bridge.start()
    await bridge.process_events()

    assert await bridge.receive_audio_frame() == pcm


async def test_bridge_receive_audio_frame_returns_none_when_queue_empty():
    connection = FakeRealtimeConnection([])
    bridge = XaiRealtimeBridge(
        XaiConfig(api_key="secret", realtime_url="wss://api.x.ai/v1/realtime"),
        connection=connection,
    )

    await bridge.start()

    assert await bridge.receive_audio_frame() is None


async def test_bridge_accepts_legacy_audio_delta_event_name():
    pcm = b"\x05\x06"
    connection = FakeRealtimeConnection(
        [
            {
                "type": "response.audio.delta",
                "delta": base64.b64encode(pcm).decode("ascii"),
            }
        ]
    )
    bridge = XaiRealtimeBridge(
        XaiConfig(api_key="secret", realtime_url="wss://api.x.ai/v1/realtime"),
        connection=connection,
    )

    await bridge.process_events()

    assert await bridge.receive_audio_frame() == pcm


def test_session_update_declares_pcm16_audio_formats():
    payload = build_session_update(XaiConfig(api_key="secret"))

    assert payload["session"]["audio"] == {
        "input": {"format": {"type": "audio/pcm", "rate": XAI_AUDIO_SAMPLE_RATE}},
        "output": {"format": {"type": "audio/pcm", "rate": XAI_AUDIO_SAMPLE_RATE}},
    }
    assert "input_audio_format" not in payload["session"]
    assert "output_audio_format" not in payload["session"]


async def test_bridge_closes_connection_on_provider_error():
    connection = FakeRealtimeConnection([{"type": "error", "error": {"message": "boom"}}])
    bridge = XaiRealtimeBridge(XaiConfig(api_key="secret"), connection=connection)

    with pytest.raises(XaiRealtimeError, match="boom"):
        await bridge.process_events()

    assert connection.closed is True
