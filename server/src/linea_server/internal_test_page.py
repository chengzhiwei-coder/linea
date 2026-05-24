CONVERSATION_TEST_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Linea Conversation Test</title>
  <style>
    :root { color-scheme: light dark; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body { max-width: 880px; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }
    label { display: block; font-weight: 650; margin: 1rem 0 0.25rem; }
    input { width: 100%; box-sizing: border-box; padding: 0.65rem; font: inherit; }
    button { margin: 1rem 0.5rem 1rem 0; padding: 0.7rem 1rem; font: inherit; cursor: pointer; }
    button:disabled { cursor: not-allowed; opacity: 0.6; }
    code, pre { background: color-mix(in srgb, CanvasText 8%, Canvas); border-radius: 0.4rem; }
    code { padding: 0.1rem 0.25rem; }
    pre { min-height: 12rem; padding: 1rem; overflow: auto; white-space: pre-wrap; }
    .status { font-weight: 700; }
    .voice-activity {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr));
      gap: 1rem;
      margin: 1rem 0;
    }
    .wave-panel {
      border: 1px solid color-mix(in srgb, CanvasText 18%, Canvas);
      border-radius: 0.9rem;
      padding: 1rem;
      background: color-mix(in srgb, CanvasText 4%, Canvas);
    }
    .wave-label { display: flex; justify-content: space-between; gap: 1rem; font-weight: 700; }
    .wave-status { color: color-mix(in srgb, CanvasText 65%, Canvas); font-weight: 600; }
    .wave-bars { display: flex; align-items: center; gap: 0.35rem; height: 4rem; margin-top: 0.75rem; }
    .wave-bars span {
      flex: 1;
      min-width: 0.35rem;
      height: 1rem;
      border-radius: 999px;
      background: color-mix(in srgb, #4f46e5 58%, Canvas);
      opacity: 0.35;
      transform-origin: center;
      animation: wavePulse 1.2s ease-in-out infinite paused;
    }
    .agent-wave .wave-bars span { background: color-mix(in srgb, #0d9488 60%, Canvas); }
    .wave-bars span:nth-child(2) { animation-delay: -1s; }
    .wave-bars span:nth-child(3) { animation-delay: -0.8s; }
    .wave-bars span:nth-child(4) { animation-delay: -0.6s; }
    .wave-bars span:nth-child(5) { animation-delay: -0.4s; }
    .wave-panel.active .wave-bars span { animation-play-state: running; opacity: 0.95; }
    .wave-panel.listening .wave-bars span { animation-play-state: running; opacity: 0.55; animation-duration: 1.8s; }
    .conversation-state { font-weight: 800; }
    @keyframes wavePulse {
      0%, 100% { transform: scaleY(0.45); }
      50% { transform: scaleY(2.4); }
    }
    @media (prefers-reduced-motion: reduce) {
      .wave-bars span { animation: none; }
      .wave-panel.active .wave-bars span,
      .wave-panel.listening .wave-bars span { transform: scaleY(1.4); }
    }
    .ok { color: #16833a; }
    .warn { color: #b26b00; }
    .error { color: #c01c28; }
  </style>
</head>
<body>
  <main>
    <h1>Linea Conversation Test</h1>
    <p>
      Internal manual test page for the browser-to-Linea realtime conversation path.
      It captures microphone audio, creates a WebRTC offer, sends it to
      <code>POST /webrtc/offer</code>, and plays the returned remote audio stream.
    </p>

    <label for="token">Server bearer token</label>
    <input id="token" type="password" autocomplete="off" placeholder="Paste the token printed on first server startup">

    <div>
      <button id="startButton" type="button">Start conversation</button>
      <button id="stopButton" type="button" disabled>Stop</button>
    </div>

    <p>Status: <span id="status" class="status warn">idle</span></p>
    <section id="voiceActivity" class="voice-activity" aria-label="Voice activity">
      <div id="userWave" class="wave-panel user-wave" aria-live="polite">
        <div class="wave-label"><span>User</span><span id="userWaveStatus" class="wave-status">silent</span></div>
        <div class="wave-bars" aria-hidden="true"><span></span><span></span><span></span><span></span><span></span></div>
      </div>
      <div id="agentWave" class="wave-panel agent-wave listening" aria-live="polite">
        <div class="wave-label"><span>Agent</span><span id="agentWaveStatus" class="wave-status">idle</span></div>
        <div class="wave-bars" aria-hidden="true"><span></span><span></span><span></span><span></span><span></span></div>
      </div>
    </section>
    <p>Conversation: <span id="conversationState" class="conversation-state warn">Agent listening</span></p>
    <audio id="remoteAudio" autoplay controls></audio>

    <h2>Log</h2>
    <pre id="log" aria-live="polite"></pre>
  </main>

  <script>
    const tokenInput = document.getElementById('token');
    const startButton = document.getElementById('startButton');
    const stopButton = document.getElementById('stopButton');
    const remoteAudio = document.getElementById('remoteAudio');
    const statusEl = document.getElementById('status');
    const conversationStateEl = document.getElementById('conversationState');
    const userWave = document.getElementById('userWave');
    const agentWave = document.getElementById('agentWave');
    const userWaveStatus = document.getElementById('userWaveStatus');
    const agentWaveStatus = document.getElementById('agentWaveStatus');
    const logEl = document.getElementById('log');

    const INITIAL_GREETING_MIC_MUTE_MS = 2500;

    let peerConnection = null;
    let localStream = null;
    let currentCallId = null;
    let microphoneEnableTimer = null;
    let audioContext = null;
    let localAnalyser = null;
    let remoteAnalyser = null;
    let voiceActivityFrame = null;
    let agentHasRemoteAudio = false;

    function log(message) {
      const timestamp = new Date().toLocaleTimeString();
      logEl.textContent += `[${timestamp}] ${message}\n`;
      logEl.scrollTop = logEl.scrollHeight;
    }

    function setStatus(message, className = 'warn') {
      statusEl.textContent = message;
      statusEl.className = `status ${className}`;
    }

    function updateConversationState(message, className = 'warn') {
      conversationStateEl.textContent = message;
      conversationStateEl.className = `conversation-state ${className}`;
    }

    async function ensureAudioContext() {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (!AudioContextClass) {
        throw new Error('Web Audio API is not available in this browser.');
      }
      if (!audioContext || audioContext.state === 'closed') {
        audioContext = new AudioContextClass();
      }
      if (audioContext.state === 'suspended') {
        await audioContext.resume();
      }
      return audioContext;
    }

    async function createAnalyserForStream(stream) {
      const context = await ensureAudioContext();
      const analyser = context.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.82;
      context.createMediaStreamSource(stream).connect(analyser);
      return analyser;
    }

    function isSpeaking(analyser) {
      if (!analyser) return false;
      const samples = new Uint8Array(analyser.fftSize);
      analyser.getByteTimeDomainData(samples);
      let sumSquares = 0;
      for (const sample of samples) {
        const normalized = (sample - 128) / 128;
        sumSquares += normalized * normalized;
      }
      const rms = Math.sqrt(sumSquares / samples.length);
      return rms > 0.035;
    }

    function setWave(panel, status, active, listening = false) {
      panel.classList.toggle('active', active);
      panel.classList.toggle('listening', listening && !active);
      status.textContent = active ? 'speaking' : listening ? 'listening' : 'silent';
    }

    function sampleVoiceActivity() {
      const userSpeaking = localStream && isSpeaking(localAnalyser);
      const agentSpeaking = isSpeaking(remoteAnalyser);
      const microphoneLive = Boolean(localStream?.getAudioTracks().some((track) => track.enabled));

      setWave(userWave, userWaveStatus, Boolean(userSpeaking));
      setWave(agentWave, agentWaveStatus, agentSpeaking, microphoneLive && !agentSpeaking);

      if (agentSpeaking) {
        updateConversationState('Agent speaking', 'ok');
      } else if (userSpeaking) {
        updateConversationState('User speaking', 'ok');
      } else if (microphoneLive && agentHasRemoteAudio) {
        updateConversationState('Agent listening', 'ok');
      } else if (agentHasRemoteAudio) {
        updateConversationState('Agent speaking or greeting', 'warn');
      } else {
        updateConversationState('Agent listening', 'warn');
      }

      voiceActivityFrame = requestAnimationFrame(sampleVoiceActivity);
    }

    function startVoiceActivityMonitoring() {
      if (voiceActivityFrame === null) {
        voiceActivityFrame = requestAnimationFrame(sampleVoiceActivity);
      }
    }

    async function stopVoiceActivityMonitoring() {
      if (voiceActivityFrame !== null) {
        window.cancelAnimationFrame(voiceActivityFrame);
        voiceActivityFrame = null;
      }
      localAnalyser = null;
      remoteAnalyser = null;
      agentHasRemoteAudio = false;
      setWave(userWave, userWaveStatus, false);
      setWave(agentWave, agentWaveStatus, false, true);
      updateConversationState('Agent listening', 'warn');
      if (audioContext && audioContext.state !== 'closed') {
        await audioContext.close();
      }
      audioContext = null;
    }

    function setMicrophoneEnabled(enabled) {
      if (!localStream) return;
      for (const track of localStream.getAudioTracks()) {
        track.enabled = enabled;
      }
      log(`Microphone ${enabled ? 'enabled' : 'muted'}.`);
    }

    function clearMicrophoneEnableTimer() {
      if (microphoneEnableTimer !== null) {
        window.clearTimeout(microphoneEnableTimer);
        microphoneEnableTimer = null;
      }
    }

    function scheduleMicrophoneEnableAfterGreeting() {
      clearMicrophoneEnableTimer();
      log(`Keeping microphone muted for ${INITIAL_GREETING_MIC_MUTE_MS}ms to avoid greeting echo.`);
      microphoneEnableTimer = window.setTimeout(() => {
        microphoneEnableTimer = null;
        setMicrophoneEnabled(true);
        setStatus('connected; speak into the microphone', 'ok');
      }, INITIAL_GREETING_MIC_MUTE_MS);
    }

    async function waitForIceGatheringComplete(pc) {
      if (pc.iceGatheringState === 'complete') return;
      await new Promise((resolve) => {
        const timeoutId = window.setTimeout(resolve, 5000);
        pc.addEventListener('icegatheringstatechange', () => {
          log(`ICE gathering: ${pc.iceGatheringState}`);
          if (pc.iceGatheringState === 'complete') {
            window.clearTimeout(timeoutId);
            resolve();
          }
        });
      });
    }

    async function startConversation() {
      const token = tokenInput.value.trim();
      if (!token) {
        setStatus('token required', 'error');
        log('Paste the local server bearer token first.');
        return;
      }

      startButton.disabled = true;
      stopButton.disabled = false;
      setStatus('starting...', 'warn');

      try {
        localStream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
        });
        localAnalyser = await createAnalyserForStream(localStream);
        startVoiceActivityMonitoring();
        setMicrophoneEnabled(false);
        log('Microphone stream acquired.');

        peerConnection = new RTCPeerConnection();
        peerConnection.onconnectionstatechange = () => {
          log(`Peer connection: ${peerConnection.connectionState}`);
          if (peerConnection.connectionState === 'connected') setStatus('connected', 'ok');
          if (['failed', 'closed', 'disconnected'].includes(peerConnection.connectionState)) {
            setStatus(peerConnection.connectionState, peerConnection.connectionState === 'closed' ? 'warn' : 'error');
          }
        };
        peerConnection.ontrack = (event) => {
          log(`Remote ${event.track.kind} track received.`);
          const [remoteStream] = event.streams;
          remoteAudio.srcObject = remoteStream;
          agentHasRemoteAudio = true;
          void createAnalyserForStream(remoteStream)
            .then((analyser) => {
              if (remoteAudio.srcObject !== remoteStream || !peerConnection) return;
              remoteAnalyser = analyser;
              startVoiceActivityMonitoring();
            })
            .catch((error) => {
              log(`Voice activity monitor unavailable: ${error instanceof Error ? error.message : String(error)}`);
            });
          scheduleMicrophoneEnableAfterGreeting();
        };

        for (const track of localStream.getAudioTracks()) {
          peerConnection.addTrack(track, localStream);
        }

        const offer = await peerConnection.createOffer();
        await peerConnection.setLocalDescription(offer);
        log('Local SDP offer created. Waiting for ICE gathering to complete...');
        await waitForIceGatheringComplete(peerConnection);

        const response = await fetch('/webrtc/offer', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`,
          },
          body: JSON.stringify({ type: 'offer', sdp: peerConnection.localDescription.sdp }),
        });

        if (!response.ok) {
          const body = await response.text();
          throw new Error(`Offer rejected with HTTP ${response.status}: ${body}`);
        }

        const answer = await response.json();
        currentCallId = answer.call_id;
        log(`Answer received. call_id=${answer.call_id}`);
        await peerConnection.setRemoteDescription({ type: answer.type, sdp: answer.sdp });
        setStatus('negotiated; waiting for greeting playback', 'ok');
      } catch (error) {
        setStatus('failed', 'error');
        log(error instanceof Error ? error.message : String(error));
        await stopConversation();
      }
    }

    async function releaseServerCall() {
      const token = tokenInput.value.trim();
      if (!currentCallId || !token) return;

      const callId = currentCallId;
      currentCallId = null;
      try {
        const response = await fetch(`/webrtc/calls/${callId}`, {
          method: 'DELETE',
          headers: { 'Authorization': `Bearer ${token}` },
        });
        if (response.ok) {
          log('Server call released.');
        } else {
          const body = await response.text();
          log(`Server call release returned HTTP ${response.status}: ${body}`);
        }
      } catch (error) {
        log(`Server call release failed: ${error instanceof Error ? error.message : String(error)}`);
      }
    }

    async function stopConversation() {
      clearMicrophoneEnableTimer();
      await releaseServerCall();
      setMicrophoneEnabled(false);
      await stopVoiceActivityMonitoring();
      if (peerConnection) {
        peerConnection.close();
        peerConnection = null;
      }
      if (localStream) {
        for (const track of localStream.getTracks()) track.stop();
        localStream = null;
      }
      remoteAudio.srcObject = null;
      startButton.disabled = false;
      stopButton.disabled = true;
      if (statusEl.textContent !== 'failed') setStatus('stopped', 'warn');
      log('Conversation stopped locally and server call release was requested.');
    }

    startButton.addEventListener('click', startConversation);
    stopButton.addEventListener('click', () => { void stopConversation(); });
  </script>
</body>
</html>
"""
