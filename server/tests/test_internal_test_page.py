from linea_server.internal_test_page import CONVERSATION_TEST_HTML


def test_internal_test_page_requests_browser_echo_cancellation() -> None:
    assert "echoCancellation: true" in CONVERSATION_TEST_HTML
    assert "noiseSuppression: true" in CONVERSATION_TEST_HTML
    assert "autoGainControl: true" in CONVERSATION_TEST_HTML


def test_internal_test_page_starts_microphone_muted_until_greeting_playback_window() -> None:
    assert "setMicrophoneEnabled(false)" in CONVERSATION_TEST_HTML
    assert "scheduleMicrophoneEnableAfterGreeting" in CONVERSATION_TEST_HTML
    assert "INITIAL_GREETING_MIC_MUTE_MS" in CONVERSATION_TEST_HTML


def test_internal_test_page_cleans_up_pending_microphone_unmute_timer() -> None:
    assert "window.clearTimeout(microphoneEnableTimer)" in CONVERSATION_TEST_HTML
    assert "microphoneEnableTimer = null" in CONVERSATION_TEST_HTML
