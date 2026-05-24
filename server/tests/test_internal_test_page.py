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


def test_internal_test_page_renders_animated_voice_waves() -> None:
    assert 'id="voiceActivity"' in CONVERSATION_TEST_HTML
    assert 'class="wave-panel user-wave"' in CONVERSATION_TEST_HTML
    assert 'agent-wave' in CONVERSATION_TEST_HTML
    assert "@keyframes wavePulse" in CONVERSATION_TEST_HTML
    assert "prefers-reduced-motion: reduce" in CONVERSATION_TEST_HTML


def test_internal_test_page_indicates_speaker_and_listener_state() -> None:
    assert 'id="conversationState"' in CONVERSATION_TEST_HTML
    assert "User speaking" in CONVERSATION_TEST_HTML
    assert "Agent listening" in CONVERSATION_TEST_HTML
    assert "Agent speaking" in CONVERSATION_TEST_HTML
    assert "updateConversationState" in CONVERSATION_TEST_HTML
    assert "localAnalyser" in CONVERSATION_TEST_HTML
    assert "remoteAnalyser" in CONVERSATION_TEST_HTML
    assert "requestAnimationFrame(sampleVoiceActivity)" in CONVERSATION_TEST_HTML
