from httpx import ASGITransport, AsyncClient

from linea_server.app import create_app


async def test_health_is_public_liveness_endpoint():
    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
