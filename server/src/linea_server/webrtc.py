import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from fractions import Fraction
from typing import Protocol

from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError
from av import AudioFrame
from av.audio.resampler import AudioResampler


@dataclass(frozen=True)
class SdpAnswer:
    type: str
    sdp: str


class WebRtcService(Protocol):
    async def create_answer(self, offer_sdp: str) -> SdpAnswer:
        """Create a server SDP answer for a client offer."""
        raise NotImplementedError

    def has_live_peer_connection(self) -> bool:
        """Return whether this service still has a non-terminal peer connection."""
        raise NotImplementedError


class StubWebRtcService:
    async def create_answer(self, offer_sdp: str) -> SdpAnswer:
        _ = offer_sdp
        return SdpAnswer(type="answer", sdp="stub-answer-sdp")

    def has_live_peer_connection(self) -> bool:
        return False


class SilentAudioTrack(MediaStreamTrack):
    """Placeholder server audio track until the xAI bridge supplies real PCM frames."""

    kind = "audio"

    def __init__(self) -> None:
        super().__init__()
        self._timestamp = 0
        self._sample_rate = 48_000
        self._samples_per_frame = 960

    async def recv(self) -> AudioFrame:
        await asyncio.sleep(self._samples_per_frame / self._sample_rate)
        frame = make_pcm16_audio_frame(
            bytes(self._samples_per_frame * 2),
            sample_rate=self._sample_rate,
            pts=self._timestamp,
        )
        self._timestamp += self._samples_per_frame
        return frame


def audio_frame_to_pcm16(frame: AudioFrame) -> bytes:
    """Return mono PCM16 bytes without codec/resampler buffer padding."""

    if frame.format.name != "s16" or frame.layout.name != "mono":
        resampler = AudioResampler(format="s16", layout="mono", rate=frame.sample_rate)
        frames = resampler.resample(frame)
        if not frames:
            return b""
        frame = frames[0]

    expected_bytes = frame.samples * 2
    return bytes(frame.planes[0])[:expected_bytes]


def make_pcm16_audio_frame(pcm16: bytes, *, sample_rate: int = 48_000, pts: int = 0) -> AudioFrame:
    samples = max(1, len(pcm16) // 2)
    frame = AudioFrame(format="s16", layout="mono", samples=samples)
    frame.planes[0].update(pcm16[: frame.planes[0].buffer_size].ljust(frame.planes[0].buffer_size, b"\x00"))
    frame.pts = pts
    frame.sample_rate = sample_rate
    frame.time_base = Fraction(1, sample_rate)
    return frame


AudioSink = Callable[[bytes], Awaitable[None]]
AudioSource = Callable[[], Awaitable[bytes | None]]
ActivityRecorder = Callable[[], None]


class PcmOutputAudioTrack(MediaStreamTrack):
    """Server audio track backed by PCM16 bytes from the xAI realtime bridge.

    Uses a small jitter buffer so brief gaps in provider chunk arrival do not
    insert silence inside an utterance. Playback starts only after the buffer
    has accumulated ``prebuffer_frames`` frames; on underflow we emit silence
    and re-enter the prebuffer state until enough audio has queued up again.
    """

    kind = "audio"

    _RESYNC_LAG_FRAMES = 5

    def __init__(
        self,
        audio_source: AudioSource,
        *,
        sample_rate: int = 48_000,
        record_activity: ActivityRecorder | None = None,
        prebuffer_frames: int = 3,
    ) -> None:
        super().__init__()
        if prebuffer_frames < 1:
            raise ValueError("prebuffer_frames must be >= 1")
        self._audio_source = audio_source
        self._sample_rate = sample_rate
        self._record_activity = record_activity
        self._timestamp = 0
        self._samples_per_frame = 960
        self._bytes_per_frame = self._samples_per_frame * 2
        self._frame_duration_seconds = self._samples_per_frame / self._sample_rate
        self._prebuffer_target_bytes = prebuffer_frames * self._bytes_per_frame
        self._pcm_buffer = bytearray()
        self._playing = False
        self._next_recv_deadline: float | None = None

    async def recv(self) -> AudioFrame:
        await self._wait_for_next_frame_deadline()

        received_audio = False
        while len(self._pcm_buffer) < self._prebuffer_target_bytes:
            pcm16 = await self._audio_source()
            if not pcm16:
                break
            self._pcm_buffer.extend(pcm16)
            received_audio = True
        if received_audio and self._record_activity is not None:
            self._record_activity()

        if not self._playing:
            if len(self._pcm_buffer) >= self._prebuffer_target_bytes:
                self._playing = True
            else:
                return self._emit_silence_frame()

        if len(self._pcm_buffer) >= self._bytes_per_frame:
            pcm16 = bytes(self._pcm_buffer[: self._bytes_per_frame])
            del self._pcm_buffer[: self._bytes_per_frame]
        else:
            self._playing = False
            return self._emit_silence_frame()

        frame = make_pcm16_audio_frame(pcm16, sample_rate=self._sample_rate, pts=self._timestamp)
        self._timestamp += frame.samples
        return frame

    def _emit_silence_frame(self) -> AudioFrame:
        frame = make_pcm16_audio_frame(
            bytes(self._bytes_per_frame),
            sample_rate=self._sample_rate,
            pts=self._timestamp,
        )
        self._timestamp += frame.samples
        return frame

    async def _wait_for_next_frame_deadline(self) -> None:
        loop = asyncio.get_event_loop()
        now = loop.time()
        if self._next_recv_deadline is None:
            self._next_recv_deadline = now
        self._next_recv_deadline += self._frame_duration_seconds
        delay = self._next_recv_deadline - loop.time()
        if delay > 0:
            await asyncio.sleep(delay)
            return
        if delay < -self._frame_duration_seconds * self._RESYNC_LAG_FRAMES:
            self._next_recv_deadline = loop.time() + self._frame_duration_seconds


class AiortcWebRtcService:
    """aiortc-backed WebRTC answer service for REST SDP offer/answer signaling."""

    def __init__(
        self,
        *,
        ice_gathering_timeout_seconds: float = 2.0,
        audio_sink: AudioSink | None = None,
        audio_source: AudioSource | None = None,
        record_activity: ActivityRecorder | None = None,
    ) -> None:
        self._ice_gathering_timeout_seconds = ice_gathering_timeout_seconds
        self._audio_sink = audio_sink
        self._audio_source = audio_source
        self._record_activity = record_activity
        self._peer_connections: set[RTCPeerConnection] = set()
        self._track_tasks: set[asyncio.Task[None]] = set()

    async def create_answer(self, offer_sdp: str) -> SdpAnswer:
        peer_connection = RTCPeerConnection()
        self._peer_connections.add(peer_connection)
        if self._audio_source is None:
            peer_connection.addTrack(SilentAudioTrack())
        else:
            peer_connection.addTrack(
                PcmOutputAudioTrack(self._audio_source, record_activity=self._record_activity)
            )

        @peer_connection.on("track")
        def on_track(track: MediaStreamTrack) -> None:
            if track.kind == "audio" and self._audio_sink is not None:
                task = asyncio.create_task(
                    self._consume_audio_track(track, self._audio_sink, self._record_activity)
                )
                self._track_tasks.add(task)
                task.add_done_callback(self._track_tasks.discard)

        await peer_connection.setRemoteDescription(
            RTCSessionDescription(sdp=offer_sdp, type="offer")
        )
        answer = await peer_connection.createAnswer()
        await peer_connection.setLocalDescription(answer)
        await self._wait_for_ice_gathering(peer_connection)

        local_description = peer_connection.localDescription
        return SdpAnswer(type=local_description.type, sdp=local_description.sdp)

    def has_live_peer_connection(self) -> bool:
        terminal_states = {"closed", "failed", "disconnected"}
        return any(
            peer_connection.connectionState not in terminal_states
            for peer_connection in self._peer_connections
        )

    async def close(self) -> None:
        for task in list(self._track_tasks):
            task.cancel()
        if self._track_tasks:
            await asyncio.gather(*self._track_tasks, return_exceptions=True)
        self._track_tasks.clear()

        peer_connections = list(self._peer_connections)
        self._peer_connections.clear()
        await asyncio.gather(
            *(peer_connection.close() for peer_connection in peer_connections), return_exceptions=True
        )

    async def _consume_audio_track(
        self,
        track: MediaStreamTrack,
        audio_sink: AudioSink,
        record_activity: ActivityRecorder | None = None,
        *,
        max_frames: int | None = None,
    ) -> None:
        frames_consumed = 0
        activity_recorder = record_activity or self._record_activity
        while max_frames is None or frames_consumed < max_frames:
            try:
                frame = await track.recv()
            except MediaStreamError:
                return
            await audio_sink(audio_frame_to_pcm16(frame))
            if activity_recorder is not None:
                activity_recorder()
            frames_consumed += 1

    async def _wait_for_ice_gathering(self, peer_connection: RTCPeerConnection) -> None:
        if peer_connection.iceGatheringState == "complete":
            return

        complete = asyncio.Event()

        @peer_connection.on("icegatheringstatechange")
        def on_ice_gathering_state_change() -> None:
            if peer_connection.iceGatheringState == "complete":
                complete.set()

        with suppress(TimeoutError):
            await asyncio.wait_for(complete.wait(), timeout=self._ice_gathering_timeout_seconds)
