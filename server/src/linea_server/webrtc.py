import asyncio
from contextlib import suppress
from dataclasses import dataclass
from fractions import Fraction
from typing import Protocol

from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from av import AudioFrame


@dataclass(frozen=True)
class SdpAnswer:
    type: str
    sdp: str


class WebRtcService(Protocol):
    async def create_answer(self, offer_sdp: str) -> SdpAnswer:
        """Create a server SDP answer for a client offer."""
        raise NotImplementedError


class StubWebRtcService:
    async def create_answer(self, offer_sdp: str) -> SdpAnswer:
        _ = offer_sdp
        return SdpAnswer(type="answer", sdp="stub-answer-sdp")


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
        frame = AudioFrame(format="s16", layout="mono", samples=self._samples_per_frame)
        for plane in frame.planes:
            plane.update(bytes(plane.buffer_size))
        frame.pts = self._timestamp
        frame.sample_rate = self._sample_rate
        frame.time_base = Fraction(1, self._sample_rate)
        self._timestamp += self._samples_per_frame
        return frame


class AiortcWebRtcService:
    """aiortc-backed WebRTC answer service for REST SDP offer/answer signaling."""

    def __init__(self, *, ice_gathering_timeout_seconds: float = 2.0) -> None:
        self._ice_gathering_timeout_seconds = ice_gathering_timeout_seconds
        self._peer_connections: set[RTCPeerConnection] = set()

    async def create_answer(self, offer_sdp: str) -> SdpAnswer:
        peer_connection = RTCPeerConnection()
        self._peer_connections.add(peer_connection)
        peer_connection.addTrack(SilentAudioTrack())

        await peer_connection.setRemoteDescription(
            RTCSessionDescription(sdp=offer_sdp, type="offer")
        )
        answer = await peer_connection.createAnswer()
        await peer_connection.setLocalDescription(answer)
        await self._wait_for_ice_gathering(peer_connection)

        local_description = peer_connection.localDescription
        return SdpAnswer(type=local_description.type, sdp=local_description.sdp)

    async def close(self) -> None:
        peer_connections = list(self._peer_connections)
        self._peer_connections.clear()
        await asyncio.gather(
            *(peer_connection.close() for peer_connection in peer_connections), return_exceptions=True
        )

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
