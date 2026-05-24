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
    async def audio_source() -> bytes:
        return b"\x01\x00\x02\x00"

    track = PcmOutputAudioTrack(audio_source)

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

    track = PcmOutputAudioTrack(audio_source)

    first_frame = await track.recv()
    second_frame = await track.recv()

    assert first_frame.samples == 960
    assert second_frame.samples == 960
    assert audio_frame_to_pcm16(first_frame) == b"\x01\x00" * 960
    assert audio_frame_to_pcm16(second_frame) == b"\x01\x00" * 960
    assert calls == 1


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
