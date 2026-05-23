from linea_server.webrtc import StubWebRtcService


async def test_stub_webrtc_service_returns_answer():
    service = StubWebRtcService()

    answer = await service.create_answer("fake-offer-sdp")

    assert answer.type == "answer"
    assert answer.sdp
