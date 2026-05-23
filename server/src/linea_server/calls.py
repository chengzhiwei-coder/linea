from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from pydantic import BaseModel, Field


DEFAULT_IDLE_TIMEOUT = timedelta(minutes=10)
Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


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
    last_activity_at: datetime | None = None
    idle_timeout: timedelta = DEFAULT_IDLE_TIMEOUT
    clock: Clock = field(default=utc_now, repr=False)

    def reserve_call(self) -> str:
        if self.active_call_id is not None:
            raise RuntimeError("call already active")
        self.active_call_id = str(uuid4())
        self.last_activity_at = self.clock()
        return self.active_call_id

    def release_call(self, call_id: str) -> None:
        if self.active_call_id == call_id:
            self.active_call_id = None
            self.last_activity_at = None

    def record_activity(self, call_id: str | None = None) -> None:
        if self.active_call_id is None:
            return
        if call_id is not None and call_id != self.active_call_id:
            return
        self.last_activity_at = self.clock()

    def is_idle(self, call_id: str | None = None, *, now: datetime | None = None) -> bool:
        if self.active_call_id is None or self.last_activity_at is None:
            return False
        if call_id is not None and call_id != self.active_call_id:
            return False
        return (now or self.clock()) - self.last_activity_at >= self.idle_timeout
