import asyncio
import logging
from contextlib import suppress

from aiortc import RTCPeerConnection
from httpx import ASGITransport, AsyncClient

from linea_server.app import create_app, end_active_call
from linea_server.db import initialize_db
from linea_server.tool_logs import finish_tool_call, start_tool_call


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
    call_id = app.state.call_manager.active_call_id
    if call_id is not None:
        await end_active_call(app, call_id)
        idle_timeout_task = app.state.idle_timeout_task
        if idle_timeout_task is not None:
            idle_timeout_task.cancel()
            with suppress(asyncio.CancelledError):
                await idle_timeout_task
            app.state.idle_timeout_task = None
        return
    close = getattr(app.state.webrtc_service, "close", None)
    if close is not None:
        await close()


async def test_auth_logs_success_and_failure_without_tokens(tmp_path, caplog):
    app = create_app(db_path=tmp_path / "linea.db")
    token = app.state.initial_server_token
    assert token is not None

    caplog.set_level(logging.INFO)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/auth/check", headers={"Authorization": "Bearer wrong-secret"})
        await client.get("/auth/check", headers={"Authorization": f"Bearer {token}"})

    log_text = caplog.text
    assert "auth failure" in log_text
    assert "auth success" in log_text
    assert token not in log_text
    assert "wrong-secret" not in log_text


async def test_call_logs_start_without_sdp(tmp_path, caplog):
    app = create_app(db_path=tmp_path / "linea.db")
    token = app.state.initial_server_token
    assert token is not None
    offer_sdp = await create_audio_offer_sdp()

    caplog.set_level(logging.INFO)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/webrtc/offer",
            headers={"Authorization": f"Bearer {token}"},
            json={"type": "offer", "sdp": offer_sdp},
        )

    assert response.status_code == 200
    log_text = caplog.text
    assert "call start" in log_text
    assert response.json()["call_id"] in log_text
    assert offer_sdp not in log_text
    assert response.json()["sdp"] not in log_text
    await close_webrtc_service(app)


async def test_call_logs_answer_creation_errors_without_sdp(tmp_path, caplog):
    app = create_app(db_path=tmp_path / "linea.db")
    token = app.state.initial_server_token
    assert token is not None

    caplog.set_level(logging.INFO)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/webrtc/offer",
            headers={"Authorization": f"Bearer {token}"},
            json={"type": "offer", "sdp": "sensitive-offer-sdp"},
        )

    assert response.status_code == 500
    log_text = caplog.text
    assert "call error" in log_text
    assert "sensitive-offer-sdp" not in log_text
    await close_webrtc_service(app)


def test_tool_logs_include_name_and_status_without_results(tmp_path, caplog):
    db_path = tmp_path / "linea.db"
    initialize_db(db_path)

    caplog.set_level(logging.INFO)
    tool_call_id = start_tool_call(db_path, "call-1", "get_current_time")
    finish_tool_call(db_path, tool_call_id, "success")

    log_text = caplog.text
    assert "tool call started" in log_text
    assert "tool call finished" in log_text
    assert "get_current_time" in log_text
    assert "success" in log_text
    assert "2026-05-23T14:05:00+03:00" not in log_text
