from dataclasses import dataclass
import os


DEFAULT_XAI_REALTIME_URL = "wss://api.x.ai/v1/realtime"
DEFAULT_XAI_REALTIME_MODEL = "grok-voice-think-fast-1.0"
DEFAULT_XAI_REALTIME_VOICE = "eve"


@dataclass(frozen=True)
class XaiConfig:
    api_key: str
    realtime_url: str = DEFAULT_XAI_REALTIME_URL
    model: str = DEFAULT_XAI_REALTIME_MODEL
    voice: str = DEFAULT_XAI_REALTIME_VOICE


def load_xai_config() -> XaiConfig:
    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        raise RuntimeError("XAI_API_KEY is required for xAI realtime voice")

    return XaiConfig(
        api_key=api_key,
        realtime_url=os.getenv("XAI_REALTIME_URL", DEFAULT_XAI_REALTIME_URL),
        model=os.getenv("XAI_REALTIME_MODEL", DEFAULT_XAI_REALTIME_MODEL),
        voice=os.getenv("XAI_REALTIME_VOICE", DEFAULT_XAI_REALTIME_VOICE),
    )
