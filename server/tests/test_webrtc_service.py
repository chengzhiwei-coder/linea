from aiortc import RTCPeerConnection, RTCSessionDescription

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


def test_audio_frame_to_pcm16_packs_frame_for_xai_input():
    frame = make_pcm16_audio_frame(b"\x03\x00\x04\x00")

    assert audio_frame_to_pcm16(frame).startswith(b"\x03\x00\x04\x00")


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
