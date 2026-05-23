from dataclasses import dataclass
from typing import Protocol


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
