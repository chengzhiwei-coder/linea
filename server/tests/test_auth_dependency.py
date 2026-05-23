from httpx import ASGITransport, AsyncClient

from linea_server.app import create_app


async def test_auth_check_rejects_missing_auth(tmp_path):
    app = create_app(db_path=tmp_path / "linea.db")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/auth/check")

    assert response.status_code == 401


async def test_auth_check_rejects_malformed_auth(tmp_path):
    app = create_app(db_path=tmp_path / "linea.db")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/auth/check", headers={"Authorization": "Token wrong"})

    assert response.status_code == 401


async def test_auth_check_rejects_invalid_auth(tmp_path):
    app = create_app(db_path=tmp_path / "linea.db")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/auth/check", headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_auth_check_accepts_valid_auth(tmp_path):
    app = create_app(db_path=tmp_path / "linea.db")
    token = app.state.initial_server_token
    assert token is not None

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/auth/check", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
