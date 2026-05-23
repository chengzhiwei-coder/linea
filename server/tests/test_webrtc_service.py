from aiortc import RTCPeerConnection, RTCSessionDescription

from linea_server.webrtc import AiortcWebRtcService, StubWebRtcService


async def test_stub_webrtc_service_returns_answer():
    service = StubWebRtcService()

    answer = await service.create_answer("fake-offer-sdp")

    assert answer.type == "answer"
    assert answer.sdp


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
