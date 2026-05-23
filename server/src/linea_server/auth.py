import hmac
from pathlib import Path
import sqlite3

from linea_server.db import DEFAULT_DB_PATH, hash_token


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
