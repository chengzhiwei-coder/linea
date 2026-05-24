from linea_server.xai_config import XaiConfig
from linea_server.xai_realtime import XAI_AUDIO_SAMPLE_RATE, build_session_update


def test_build_session_update_declares_model_voice_and_time_tool():
    payload = build_session_update(
        XaiConfig(
            api_key="secret",
            realtime_url="wss://api.x.ai/v1/realtime",
            model="grok-voice-think-fast-1.0",
            voice="eve",
        )
    )

    assert payload["type"] == "session.update"
    assert payload["session"]["model"] == "grok-voice-think-fast-1.0"
    assert payload["session"]["voice"] == "eve"
    assert payload["session"]["audio"] == {
        "input": {"format": {"type": "audio/pcm", "rate": XAI_AUDIO_SAMPLE_RATE}},
        "output": {"format": {"type": "audio/pcm", "rate": XAI_AUDIO_SAMPLE_RATE}},
    }
    assert "input_audio_format" not in payload["session"]
    assert "output_audio_format" not in payload["session"]
    assert payload["session"]["tools"][0]["name"] == "get_current_time"
