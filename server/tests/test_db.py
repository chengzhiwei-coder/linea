import sqlite3

from linea_server.db import hash_token, initialize_db


def table_names(db_path):
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {row[0] for row in rows}


def test_initialize_db_creates_required_tables(tmp_path):
    db_path = tmp_path / "linea.db"

    result = initialize_db(db_path)

    assert result.created_new_server_token is True
    assert result.plaintext_server_token is not None
    assert table_names(db_path) >= {"server_auth", "tool_calls"}


def test_initialize_db_stores_server_token_hash_only(tmp_path):
    db_path = tmp_path / "linea.db"

    result = initialize_db(db_path)

    assert result.plaintext_server_token is not None
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT token_hash FROM server_auth WHERE id = 1").fetchone()
        plaintext_matches = conn.execute(
            "SELECT 1 FROM server_auth WHERE token_hash = ?",
            (result.plaintext_server_token,),
        ).fetchone()

    assert row == (hash_token(result.plaintext_server_token),)
    assert plaintext_matches is None


def test_initialize_db_only_returns_plaintext_token_once(tmp_path):
    db_path = tmp_path / "linea.db"

    first = initialize_db(db_path)
    second = initialize_db(db_path)

    assert first.created_new_server_token is True
    assert first.plaintext_server_token is not None
    assert second.created_new_server_token is False
    assert second.plaintext_server_token is None
