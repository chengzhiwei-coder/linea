from httpx import ASGITransport, AsyncClient

from linea_server.app import create_app


async def test_internal_conversation_test_page_is_served_for_manual_webrtc_verification(tmp_path):
    app = create_app(db_path=tmp_path / "linea.db")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/internal/conversation-test")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    assert "Linea Conversation Test" in html
    assert "navigator.mediaDevices.getUserMedia" in html
    assert "RTCPeerConnection" in html
    assert "fetch('/webrtc/offer'" in html
    assert "fetch(`/webrtc/calls/${callId}`" in html
    assert "Authorization': `Bearer ${token}`" in html
    assert "id=\"remoteAudio\"" in html
    assert "Server call released." in html
