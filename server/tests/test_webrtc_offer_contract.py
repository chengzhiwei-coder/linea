from httpx import ASGITransport, AsyncClient

from linea_server.app import create_app


async def test_webrtc_offer_requires_auth(tmp_path):
    app = create_app(db_path=tmp_path / "linea.db")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/webrtc/offer", json={"type": "offer", "sdp": "fake"})

    assert response.status_code == 401


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


async def test_webrtc_offer_returns_stub_answer_for_valid_offer(tmp_path):
    app = create_app(db_path=tmp_path / "linea.db")
    token = app.state.initial_server_token

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/webrtc/offer",
            headers={"Authorization": f"Bearer {token}"},
            json={"type": "offer", "sdp": "fake-sdp"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "answer"
    assert body["call_id"]
    assert isinstance(body["sdp"], str)


async def test_webrtc_offer_rejects_second_active_call(tmp_path):
    app = create_app(db_path=tmp_path / "linea.db")
    token = app.state.initial_server_token
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"type": "offer", "sdp": "fake-sdp"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/webrtc/offer", headers=headers, json=payload)
        second = await client.post("/webrtc/offer", headers=headers, json=payload)

    assert first.status_code == 200
    assert second.status_code == 409
