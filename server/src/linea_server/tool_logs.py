from pathlib import Path
import sqlite3


VALID_FINAL_STATUSES = {"success", "error", "cancelled"}


def start_tool_call(db_path: Path, call_id: str, tool_name: str) -> int:
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO tool_calls (call_id, tool_name, status) VALUES (?, ?, 'started')",
            (call_id, tool_name),
        )
        conn.commit()
        if cursor.lastrowid is None:
            raise RuntimeError("failed to create tool call log row")
        return cursor.lastrowid


def finish_tool_call(db_path: Path, tool_call_id: int, status: str) -> None:
    if status not in VALID_FINAL_STATUSES:
        raise ValueError(f"invalid final tool status: {status}")

    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE tool_calls
            SET status = ?, finished_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'started'
            """,
            (status, tool_call_id),
        )
        conn.commit()
        if cursor.rowcount != 1:
            raise ValueError(f"tool call log row not found or already finished: {tool_call_id}")
