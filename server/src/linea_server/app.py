from pathlib import Path

from fastapi import Depends, FastAPI

from linea_server.auth import require_bearer_auth
from linea_server.db import DEFAULT_DB_PATH, initialize_db


def create_app(db_path: Path = DEFAULT_DB_PATH) -> FastAPI:
    init_result = initialize_db(db_path)

    app = FastAPI(title="Linea Server", version="0.1.0")
    app.state.db_path = db_path
    app.state.initial_server_token = init_result.plaintext_server_token

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/auth/check", dependencies=[Depends(require_bearer_auth)])
    async def auth_check() -> dict[str, bool]:
        return {"ok": True}

    return app
