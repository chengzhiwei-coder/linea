import base64

import pytest

from linea_server.xai_config import XaiConfig
from linea_server.xai_realtime import XaiRealtimeBridge, XaiRealtimeError, build_session_update


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


async def test_bridge_receives_xai_audio_delta_for_webrtc_output():
    pcm = b"\x03\x04"
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

    await bridge.start()
    await bridge.process_events()

    assert await bridge.receive_audio_frame() == pcm


def test_session_update_declares_pcm16_audio_formats():
    payload = build_session_update(XaiConfig(api_key="secret"))

    assert payload["session"]["input_audio_format"] == "pcm16"
    assert payload["session"]["output_audio_format"] == "pcm16"


async def test_bridge_closes_connection_on_provider_error():
    connection = FakeRealtimeConnection([{"type": "error", "error": {"message": "boom"}}])
    bridge = XaiRealtimeBridge(XaiConfig(api_key="secret"), connection=connection)

    with pytest.raises(XaiRealtimeError, match="boom"):
        await bridge.process_events()

    assert connection.closed is True
