from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from linea_server.app import monitor_idle_call
from linea_server.calls import CallManager
from linea_server.webrtc import PcmOutputAudioTrack, audio_frame_to_pcm16, make_pcm16_audio_frame
from linea_server.xai_realtime import XaiRealtimeBridge
from linea_server.xai_config import XaiConfig


START = datetime(2026, 1, 1, tzinfo=UTC)


def test_new_call_stores_last_activity_timestamp():
    manager = CallManager(clock=lambda: START)

    call_id = manager.reserve_call()

    assert manager.active_call_id == call_id
    assert manager.last_activity_at == START


def test_record_activity_updates_timestamp():
    current_time = START
    manager = CallManager(clock=lambda: current_time)
    call_id = manager.reserve_call()

    current_time = START + timedelta(seconds=30)
    manager.record_activity(call_id)

    assert manager.last_activity_at == START + timedelta(seconds=30)


@pytest.mark.parametrize(
    ("elapsed", "expected"),
    [
        (timedelta(minutes=9, seconds=59), False),
        (timedelta(minutes=10), True),
        (timedelta(minutes=10, seconds=1), True),
    ],
)
def test_call_is_idle_after_ten_minutes_without_activity(elapsed, expected):
    manager = CallManager(clock=lambda: START)
    call_id = manager.reserve_call()

    assert manager.is_idle(call_id, now=START + elapsed) is expected


def test_activity_for_stale_or_released_call_is_ignored():
    manager = CallManager(clock=lambda: START)
    call_id = manager.reserve_call()
    manager.release_call(call_id)

    manager.record_activity(call_id)

    assert manager.last_activity_at is None
    assert manager.is_idle(call_id, now=START + timedelta(minutes=11)) is False


async def test_webrtc_inbound_audio_frame_records_activity():
    calls = 0

    async def audio_sink(pcm16: bytes) -> None:
        assert pcm16.startswith(b"\x01\x00")

    def record_activity() -> None:
        nonlocal calls
        calls += 1

    class OneFrameTrack:
        kind = "audio"

        async def recv(self):
            return make_pcm16_audio_frame(b"\x01\x00")

    from linea_server.webrtc import AiortcWebRtcService

    service = AiortcWebRtcService(audio_sink=audio_sink, record_activity=record_activity)
    await service._consume_audio_track(OneFrameTrack(), audio_sink, max_frames=1)

    assert calls == 1


async def test_webrtc_outbound_audio_frame_records_activity():
    calls = 0

    async def audio_source() -> bytes:
        return b"\x02\x00"

    def record_activity() -> None:
        nonlocal calls
        calls += 1

    track = PcmOutputAudioTrack(audio_source, record_activity=record_activity)

    frame = await track.recv()

    assert audio_frame_to_pcm16(frame).startswith(b"\x02\x00")
    assert calls == 1


class FakeRealtimeConnection:
    def __init__(self, events):
        self.sent = []
        self._events = events

    async def send_json(self, payload):
        self.sent.append(payload)

    async def __aiter__(self):
        for event in self._events:
            yield event

    async def close(self):
        pass


def xai_config() -> XaiConfig:
    return XaiConfig(
        api_key="test-key",
        realtime_url="wss://example.invalid/realtime",
        model="grok-voice-test",
        voice="test-voice",
    )


async def test_xai_inbound_audio_event_records_activity():
    calls = 0

    def record_activity() -> None:
        nonlocal calls
        calls += 1

    bridge = XaiRealtimeBridge(
        xai_config(),
        connection=FakeRealtimeConnection([
            {"type": "response.audio.delta", "delta": "AQI="},
        ]),
        record_activity=record_activity,
    )

    await bridge.process_events()

    assert await bridge.receive_audio_frame() == b"\x01\x02"
    assert calls == 2


async def test_xai_session_event_records_activity():
    calls = 0

    def record_activity() -> None:
        nonlocal calls
        calls += 1

    bridge = XaiRealtimeBridge(
        xai_config(),
        connection=FakeRealtimeConnection([
            {"type": "session.updated"},
        ]),
        record_activity=record_activity,
    )

    await bridge.process_events()

    assert calls == 2


async def test_idle_monitor_releases_active_call_and_closes_resources():
    closed = []

    class FakeClosable:
        async def close(self) -> None:
            closed.append(type(self).__name__)

    manager = CallManager(clock=lambda: START, idle_timeout=timedelta(seconds=0))
    call_id = manager.reserve_call()
    app = SimpleNamespace(
        state=SimpleNamespace(
            call_manager=manager,
            xai_event_task=None,
            xai_bridge=FakeClosable(),
            webrtc_service=FakeClosable(),
        )
    )

    await monitor_idle_call(app, call_id, poll_interval_seconds=0)

    assert manager.active_call_id is None
    assert manager.last_activity_at is None
    assert closed == ["FakeClosable", "FakeClosable"]
