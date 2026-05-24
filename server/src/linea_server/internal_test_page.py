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
    const logEl = document.getElementById('log');

    const INITIAL_GREETING_MIC_MUTE_MS = 2500;

    let peerConnection = null;
    let localStream = null;
    let currentCallId = null;
    let microphoneEnableTimer = null;

    function log(message) {
      const timestamp = new Date().toLocaleTimeString();
      logEl.textContent += `[${timestamp}] ${message}\n`;
      logEl.scrollTop = logEl.scrollHeight;
    }

    function setStatus(message, className = 'warn') {
      statusEl.textContent = message;
      statusEl.className = `status ${className}`;
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
          remoteAudio.srcObject = event.streams[0];
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
