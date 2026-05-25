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
    assert table_names(db_path) >= {"server_auth", "tool_calls", "hermes_jobs"}


def test_initialize_db_stores_server_token_for_restart_display(tmp_path):
    db_path = tmp_path / "linea.db"

    result = initialize_db(db_path)

    assert result.plaintext_server_token is not None
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT token, token_hash FROM server_auth WHERE id = 1"
        ).fetchone()

    assert row == (
        result.plaintext_server_token,
        hash_token(result.plaintext_server_token),
    )


def test_initialize_db_returns_plaintext_token_on_every_start(tmp_path):
    db_path = tmp_path / "linea.db"

    first = initialize_db(db_path)
    second = initialize_db(db_path)

    assert first.created_new_server_token is True
    assert first.plaintext_server_token is not None
    assert second.created_new_server_token is False
    assert second.plaintext_server_token == first.plaintext_server_token


def test_initialize_db_rotates_legacy_hash_only_token(tmp_path):
    db_path = tmp_path / "linea.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE server_auth (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                token_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "INSERT INTO server_auth (id, token_hash) VALUES (1, ?)",
            (hash_token("legacy-token"),),
        )

    result = initialize_db(db_path)

    assert result.created_new_server_token is False
    assert result.plaintext_server_token is not None
    assert result.plaintext_server_token != "legacy-token"
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT token, token_hash FROM server_auth WHERE id = 1"
        ).fetchone()
    assert row == (
        result.plaintext_server_token,
        hash_token(result.plaintext_server_token),
    )
