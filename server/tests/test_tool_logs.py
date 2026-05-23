import sqlite3

import pytest

from linea_server.db import initialize_db
from linea_server.tool_logs import finish_tool_call, start_tool_call


def test_tool_call_log_lifecycle(tmp_path):
    db_path = tmp_path / "linea.db"
    initialize_db(db_path)

    tool_call_id = start_tool_call(db_path, "call-1", "get_current_time")

    with sqlite3.connect(db_path) as conn:
        started_row = conn.execute(
            "SELECT call_id, tool_name, status, started_at, finished_at FROM tool_calls WHERE id = ?",
            (tool_call_id,),
        ).fetchone()

    assert started_row[0] == "call-1"
    assert started_row[1] == "get_current_time"
    assert started_row[2] == "started"
    assert started_row[3] is not None
    assert started_row[4] is None

    finish_tool_call(db_path, tool_call_id, "success")

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT call_id, tool_name, status, finished_at FROM tool_calls WHERE id = ?",
            (tool_call_id,),
        ).fetchone()

    assert row[0] == "call-1"
    assert row[1] == "get_current_time"
    assert row[2] == "success"
    assert row[3] is not None


@pytest.mark.parametrize("status", ["success", "error", "cancelled"])
def test_finish_tool_call_accepts_final_statuses(tmp_path, status):
    db_path = tmp_path / "linea.db"
    initialize_db(db_path)
    tool_call_id = start_tool_call(db_path, "call-1", "get_current_time")

    finish_tool_call(db_path, tool_call_id, status)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT status FROM tool_calls WHERE id = ?", (tool_call_id,)).fetchone()

    assert row == (status,)


def test_finish_tool_call_rejects_invalid_status(tmp_path):
    db_path = tmp_path / "linea.db"
    initialize_db(db_path)
    tool_call_id = start_tool_call(db_path, "call-1", "get_current_time")

    with pytest.raises(ValueError, match="invalid final tool status"):
        finish_tool_call(db_path, tool_call_id, "started")


def test_finish_tool_call_rejects_missing_or_already_finished_rows(tmp_path):
    db_path = tmp_path / "linea.db"
    initialize_db(db_path)
    tool_call_id = start_tool_call(db_path, "call-1", "get_current_time")

    with pytest.raises(ValueError, match="not found or already finished"):
        finish_tool_call(db_path, tool_call_id + 1, "success")

    finish_tool_call(db_path, tool_call_id, "success")

    with pytest.raises(ValueError, match="not found or already finished"):
        finish_tool_call(db_path, tool_call_id, "error")
