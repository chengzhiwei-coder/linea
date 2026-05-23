from dataclasses import dataclass
from uuid import uuid4

from pydantic import BaseModel, Field


class WebRtcOfferRequest(BaseModel):
    type: str = Field(pattern="^offer$")
    sdp: str


class WebRtcOfferResponse(BaseModel):
    type: str = "answer"
    sdp: str
    call_id: str


@dataclass
class CallManager:
    active_call_id: str | None = None

    def start_placeholder_call(self) -> WebRtcOfferResponse:
        if self.active_call_id is not None:
            raise RuntimeError("call already active")
        self.active_call_id = str(uuid4())
        return WebRtcOfferResponse(
            type="answer",
            sdp="stub-answer-sdp",
            call_id=self.active_call_id,
        )
