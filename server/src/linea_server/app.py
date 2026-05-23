from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status

from linea_server.auth import require_bearer_auth
from linea_server.calls import CallManager, WebRtcOfferRequest, WebRtcOfferResponse
from linea_server.db import DEFAULT_DB_PATH, initialize_db


def create_app(db_path: Path = DEFAULT_DB_PATH) -> FastAPI:
    init_result = initialize_db(db_path)

    app = FastAPI(title="Linea Server", version="0.1.0")
    app.state.db_path = db_path
    app.state.initial_server_token = init_result.plaintext_server_token
    app.state.call_manager = CallManager()

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
        _ = offer
        try:
            return app.state.call_manager.start_placeholder_call()
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return app
