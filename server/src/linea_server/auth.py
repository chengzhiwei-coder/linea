import hmac
import logging
from pathlib import Path
import sqlite3

from fastapi import Header, HTTPException, Request, status

from linea_server.db import DEFAULT_DB_PATH, hash_token

logger = logging.getLogger(__name__)


def verify_server_token(db_path: Path = DEFAULT_DB_PATH, token: str = "") -> bool:
    if not token:
        return False

    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT token_hash FROM server_auth WHERE id = 1").fetchone()

    if row is None:
        return False

    expected_hash = row[0]
    actual_hash = hash_token(token)
    return hmac.compare_digest(actual_hash, expected_hash)


async def require_bearer_auth(
    request: Request,
    authorization: str | None = Header(default=None),
) -> None:
    if authorization is None or not authorization.startswith("Bearer "):
        logger.warning("auth failure path=%s reason=missing_or_malformed", request.url.path)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    token = authorization.removeprefix("Bearer ").strip()
    if not verify_server_token(request.app.state.db_path, token):
        logger.warning("auth failure path=%s reason=invalid_token", request.url.path)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    logger.info("auth success path=%s", request.url.path)
