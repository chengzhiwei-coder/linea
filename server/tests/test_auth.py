from linea_server.auth import verify_server_token
from linea_server.db import hash_token, initialize_db


def test_verify_server_token_accepts_matching_token(tmp_path):
    db_path = tmp_path / "linea.db"
    result = initialize_db(db_path)

    assert result.plaintext_server_token is not None
    assert verify_server_token(db_path, result.plaintext_server_token) is True


def test_verify_server_token_rejects_invalid_token(tmp_path):
    db_path = tmp_path / "linea.db"
    initialize_db(db_path)

    assert verify_server_token(db_path, "wrong") is False


def test_hash_token_is_deterministic():
    assert hash_token("abc") == hash_token("abc")
    assert hash_token("abc") != hash_token("def")
