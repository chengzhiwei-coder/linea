from linea_server.app import create_app


def test_create_app_initializes_db_at_given_path(tmp_path):
    db_path = tmp_path / "linea.db"

    app = create_app(db_path=db_path)

    assert app.state.db_path == db_path
    assert db_path.exists()
