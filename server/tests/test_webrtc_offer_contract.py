from aiortc import RTCPeerConnection
from httpx import ASGITransport, AsyncClient

from linea_server.app import create_app


async def create_audio_offer_sdp() -> str:
    client = RTCPeerConnection()
    client.addTransceiver("audio", direction="recvonly")
    offer = await client.createOffer()
    await client.setLocalDescription(offer)
    try:
        return client.localDescription.sdp
    finally:
        await client.close()


async def close_webrtc_service(app) -> None:
    close = getattr(app.state.webrtc_service, "close", None)
    if close is not None:
        await close()


async def test_webrtc_offer_requires_auth(tmp_path):
    app = create_app(db_path=tmp_path / "linea.db")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/webrtc/offer", json={"type": "offer", "sdp": "fake"})

    assert response.status_code == 401
    await close_webrtc_service(app)


async def test_webrtc_offer_validates_payload(tmp_path):
    app = create_app(db_path=tmp_path / "linea.db")
    token = app.state.initial_server_token

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/webrtc/offer",
            headers={"Authorization": f"Bearer {token}"},
            json={"type": "wrong", "sdp": "fake"},
        )

    assert response.status_code == 422
    await close_webrtc_service(app)


async def test_webrtc_offer_returns_real_answer_for_valid_offer(tmp_path):
    app = create_app(db_path=tmp_path / "linea.db")
    token = app.state.initial_server_token
    offer_sdp = await create_audio_offer_sdp()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/webrtc/offer",
            headers={"Authorization": f"Bearer {token}"},
            json={"type": "offer", "sdp": offer_sdp},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "answer"
    assert body["call_id"]
    assert "m=audio" in body["sdp"]
    assert "stub-answer-sdp" not in body["sdp"]
    assert app.state.xai_bridge._initial_greeting_text == "Hey, how can I help you?"
    assert app.state.xai_bridge._on_input_speech_started is not None
    tool_names = {schema["name"] for schema in app.state.xai_bridge._tool_registry.tool_schemas()}
    assert {"run_hermes_task", "get_hermes_status", "cancel_hermes_task"} <= tool_names
    assert app.state.xai_bridge._is_tool_call_active("provider-tool-call-id") is True
    app.state.call_manager.release_call(body["call_id"])
    assert app.state.xai_bridge._is_tool_call_active("provider-tool-call-id") is False
    await close_webrtc_service(app)


async def test_webrtc_offer_rejects_second_active_call(tmp_path):
    app = create_app(db_path=tmp_path / "linea.db")
    token = app.state.initial_server_token
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"type": "offer", "sdp": await create_audio_offer_sdp()}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/webrtc/offer", headers=headers, json=payload)
        second = await client.post("/webrtc/offer", headers=headers, json=payload)

    assert first.status_code == 200
    assert second.status_code == 409
    await close_webrtc_service(app)


async def test_manual_webrtc_stop_releases_call_before_idle_timeout(tmp_path):
    app = create_app(db_path=tmp_path / "linea.db")
    cancel_calls = []

    async def track_request_cancel():
        cancel_calls.append("request")
        return {"ok": True}

    async def track_confirm_cancel():
        cancel_calls.append("confirm")
        return {"ok": True}

    app.state.hermes_job_manager.request_cancel = track_request_cancel
    app.state.hermes_job_manager.confirm_cancel = track_confirm_cancel
    token = app.state.initial_server_token
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"type": "offer", "sdp": await create_audio_offer_sdp()}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/webrtc/offer", headers=headers, json=payload)
        call_id = first.json()["call_id"]
        stopped = await client.delete(f"/webrtc/calls/{call_id}", headers=headers)
        second = await client.post("/webrtc/offer", headers=headers, json=payload)

    assert first.status_code == 200
    assert stopped.status_code == 204
    assert second.status_code == 200
    assert second.json()["call_id"] != call_id
    assert cancel_calls == []
    await close_webrtc_service(app)


async def test_webrtc_offer_replaces_interrupted_active_call_before_idle_timeout(tmp_path):
    app = create_app(db_path=tmp_path / "linea.db")
    token = app.state.initial_server_token
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"type": "offer", "sdp": await create_audio_offer_sdp()}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/webrtc/offer", headers=headers, json=payload)
        first_call_id = first.json()["call_id"]
        for peer_connection in list(app.state.webrtc_service._peer_connections):
            await peer_connection.close()

        second = await client.post("/webrtc/offer", headers=headers, json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["call_id"] != first_call_id
    await close_webrtc_service(app)


async def test_webrtc_offer_releases_reserved_call_when_answer_creation_fails(tmp_path):
    class FailingWebRtcService:
        async def create_answer(self, offer_sdp: str):
            _ = offer_sdp
            raise RuntimeError("answer failed")

    app = create_app(db_path=tmp_path / "linea.db")
    app.state.webrtc_service = FailingWebRtcService()
    token = app.state.initial_server_token
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"type": "offer", "sdp": "fake-sdp"}

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        failed = await client.post("/webrtc/offer", headers=headers, json=payload)

    assert failed.status_code == 500
    assert app.state.call_manager.active_call_id is None
