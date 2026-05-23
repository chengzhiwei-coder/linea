import asyncio
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status

from linea_server.auth import require_bearer_auth
from linea_server.calls import CallManager, WebRtcOfferRequest, WebRtcOfferResponse
from linea_server.db import DEFAULT_DB_PATH, initialize_db
from linea_server.webrtc import AiortcWebRtcService
from linea_server.xai_config import load_xai_config
from linea_server.xai_realtime import XaiRealtimeBridge


def create_app(db_path: Path = DEFAULT_DB_PATH) -> FastAPI:
    init_result = initialize_db(db_path)

    app = FastAPI(title="Linea Server", version="0.1.0")
    app.state.db_path = db_path
    app.state.initial_server_token = init_result.plaintext_server_token
    app.state.call_manager = CallManager()
    try:
        app.state.xai_bridge = XaiRealtimeBridge(load_xai_config())
    except RuntimeError:
        app.state.xai_bridge = None
        app.state.webrtc_service = AiortcWebRtcService()
    else:
        app.state.webrtc_service = AiortcWebRtcService(
            audio_sink=app.state.xai_bridge.send_audio_frame,
            audio_source=app.state.xai_bridge.receive_audio_frame,
        )
    app.state.xai_event_task = None

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/auth/check", dependencies=[Depends(require_bearer_auth)])
    async def auth_check() -> dict[str, bool]:
        return {"ok": True}

    @app.post(
        "/webrtc/offer",
        response_model=WebRtcOfferResponse,
        dependencies=[Depends(require_bearer_auth)],
    )
    async def webrtc_offer(offer: WebRtcOfferRequest) -> WebRtcOfferResponse:
        try:
            call_id = app.state.call_manager.reserve_call()
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

        try:
            answer = await app.state.webrtc_service.create_answer(offer.sdp)
        except Exception:
            app.state.call_manager.release_call(call_id)
            raise

        if app.state.xai_bridge is not None:
            app.state.xai_event_task = asyncio.create_task(app.state.xai_bridge.process_events())
            app.state.xai_event_task.add_done_callback(
                lambda task: app.state.call_manager.release_call(call_id)
                if task.cancelled() or task.exception() is not None
                else None
            )

        return WebRtcOfferResponse(type=answer.type, sdp=answer.sdp, call_id=call_id)

    return app
