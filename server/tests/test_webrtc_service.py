from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError

from linea_server.webrtc import (
    AiortcWebRtcService,
    PcmOutputAudioTrack,
    StubWebRtcService,
    audio_frame_to_pcm16,
    make_pcm16_audio_frame,
)


async def test_stub_webrtc_service_returns_answer():
    service = StubWebRtcService()

    answer = await service.create_answer("fake-offer-sdp")

    assert answer.type == "answer"
    assert answer.sdp


async def test_pcm_output_audio_track_uses_xai_audio_source():
    chunks = [b"\x01\x00\x02\x00" + bytes(960 * 2 - 4)]

    async def audio_source() -> bytes | None:
        if chunks:
            return chunks.pop(0)
        return None

    track = PcmOutputAudioTrack(audio_source, prebuffer_frames=1)

    frame = await track.recv()

    assert audio_frame_to_pcm16(frame).startswith(b"\x01\x00\x02\x00")


async def test_pcm_output_audio_track_splits_provider_chunks_into_twenty_ms_frames():
    chunk = b"\x01\x00" * (960 * 2)
    calls = 0

    async def audio_source() -> bytes | None:
        nonlocal calls
        calls += 1
        if calls == 1:
            return chunk
        return None

    track = PcmOutputAudioTrack(audio_source, prebuffer_frames=1)

    first_frame = await track.recv()
    second_frame = await track.recv()

    assert first_frame.samples == 960
    assert second_frame.samples == 960
    assert audio_frame_to_pcm16(first_frame) == b"\x01\x00" * 960
    assert audio_frame_to_pcm16(second_frame) == b"\x01\x00" * 960


async def test_pcm_output_audio_track_coalesces_small_provider_chunks_before_emitting():
    chunks = [b"\x01\x00" * 320, b"\x02\x00" * 320, b"\x03\x00" * 320]

    async def audio_source() -> bytes | None:
        if chunks:
            return chunks.pop(0)
        return None

    track = PcmOutputAudioTrack(audio_source, prebuffer_frames=1)

    frame = await track.recv()

    assert frame.samples == 960
    assert audio_frame_to_pcm16(frame) == (
        b"\x01\x00" * 320 + b"\x02\x00" * 320 + b"\x03\x00" * 320
    )


async def test_pcm_output_audio_track_waits_for_prebuffer_before_emitting_audio():
    chunks = [b"\x01\x00" * 960, b"\x02\x00" * 960, b"\x03\x00" * 960]

    async def audio_source() -> bytes | None:
        if chunks:
            return chunks.pop(0)
        return None

    track = PcmOutputAudioTrack(audio_source, prebuffer_frames=3)

    frame = await track.recv()

    assert frame.samples == 960
    assert audio_frame_to_pcm16(frame) == b"\x01\x00" * 960


async def test_pcm_output_audio_track_emits_silence_until_prebuffer_threshold_met():
    chunks: list[bytes | None] = [
        b"\x01\x00" * 480,
        None,
        b"\x02\x00" * 480,
        None,
        b"\x03\x00" * 960,
    ]

    async def audio_source() -> bytes | None:
        if not chunks:
            return None
        return chunks.pop(0)

    track = PcmOutputAudioTrack(audio_source, prebuffer_frames=2)

    frame_one = audio_frame_to_pcm16(await track.recv())
    frame_two = audio_frame_to_pcm16(await track.recv())
    frame_three = audio_frame_to_pcm16(await track.recv())
    frame_four = audio_frame_to_pcm16(await track.recv())

    assert frame_one == bytes(960 * 2)
    assert frame_two == bytes(960 * 2)
    assert frame_three == b"\x01\x00" * 480 + b"\x02\x00" * 480
    assert frame_four == b"\x03\x00" * 960


async def test_pcm_output_audio_track_does_not_insert_silence_during_continuous_playback():
    half_frame = b"\x01\x00" * 480
    chunks: list[bytes | None] = [
        half_frame, half_frame,  # frame 1 (across 2 chunks)
        None,
        half_frame, half_frame,  # frame 2 (across 2 chunks)
        None,
        half_frame, half_frame,  # frame 3 (across 2 chunks)
        None,
        half_frame, half_frame,  # frame 4 (across 2 chunks, after prebuffer satisfied)
    ]

    async def audio_source() -> bytes | None:
        if not chunks:
            return None
        head = chunks[0]
        chunks.pop(0)
        return head

    track = PcmOutputAudioTrack(audio_source, prebuffer_frames=3)

    frames = [audio_frame_to_pcm16(await track.recv()) for _ in range(4)]

    assert frames[0] == bytes(960 * 2)
    assert frames[1] == bytes(960 * 2)
    assert frames[2] == b"\x01\x00" * 960
    assert frames[3] == b"\x01\x00" * 960


async def test_pcm_output_audio_track_re_enters_prebuffer_on_underflow():
    full_frame = b"\x01\x00" * 960
    chunks: list[bytes | None] = [full_frame, full_frame]

    async def audio_source() -> bytes | None:
        if chunks:
            return chunks.pop(0)
        return None

    track = PcmOutputAudioTrack(audio_source, prebuffer_frames=2)

    first = audio_frame_to_pcm16(await track.recv())
    second = audio_frame_to_pcm16(await track.recv())
    underflow = audio_frame_to_pcm16(await track.recv())

    chunks.append(full_frame)
    still_silent = audio_frame_to_pcm16(await track.recv())

    chunks.append(full_frame)
    resumed = audio_frame_to_pcm16(await track.recv())

    assert first == full_frame
    assert second == full_frame
    assert underflow == bytes(960 * 2)
    assert still_silent == bytes(960 * 2)
    assert resumed == full_frame


async def test_pcm_output_audio_track_rejects_zero_prebuffer():
    async def audio_source() -> bytes | None:
        return None

    try:
        PcmOutputAudioTrack(audio_source, prebuffer_frames=0)
    except ValueError:
        return
    raise AssertionError("expected ValueError for prebuffer_frames=0")


def test_audio_frame_to_pcm16_packs_frame_for_xai_input():
    frame = make_pcm16_audio_frame(b"\x03\x00\x04\x00")

    assert audio_frame_to_pcm16(frame) == b"\x03\x00\x04\x00"


def test_audio_frame_to_pcm16_downmixes_web_rtc_stereo_to_mono_without_padding():
    from av import AudioFrame

    frame = AudioFrame(format="s16", layout="stereo", samples=2)
    frame.sample_rate = 48_000
    frame.planes[0].update(
        b"\x02\x00"  # left sample 1: 2
        b"\x04\x00"  # right sample 1: 4 -> mono 3
        b"\x06\x00"  # left sample 2: 6
        b"\x08\x00"  # right sample 2: 8 -> mono 7
    )

    assert audio_frame_to_pcm16(frame) == b"\x03\x00\x07\x00"


async def test_aiortc_webrtc_service_returns_answer_for_audio_offer():
    client = RTCPeerConnection()
    client.addTransceiver("audio", direction="recvonly")
    offer = await client.createOffer()
    await client.setLocalDescription(offer)

    service = AiortcWebRtcService()
    try:
        answer = await service.create_answer(client.localDescription.sdp)
        await client.setRemoteDescription(RTCSessionDescription(sdp=answer.sdp, type=answer.type))

        assert answer.type == "answer"
        assert "m=audio" in answer.sdp
        assert client.remoteDescription is not None
    finally:
        await service.close()
        await client.close()


async def test_audio_track_end_is_handled_as_normal_shutdown():
    class EndedTrack:
        kind = "audio"

        async def recv(self):
            raise MediaStreamError

    async def audio_sink(pcm16: bytes) -> None:
        raise AssertionError(f"unexpected audio frame: {pcm16!r}")

    service = AiortcWebRtcService(audio_sink=audio_sink)

    await service._consume_audio_track(EndedTrack(), audio_sink)
