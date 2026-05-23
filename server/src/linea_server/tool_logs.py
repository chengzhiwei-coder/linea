import logging
from pathlib import Path
import sqlite3


VALID_FINAL_STATUSES = {"success", "error", "cancelled"}

logger = logging.getLogger(__name__)


def start_tool_call(db_path: Path, call_id: str, tool_name: str) -> int:
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO tool_calls (call_id, tool_name, status) VALUES (?, ?, 'started')",
            (call_id, tool_name),
        )
        conn.commit()
        if cursor.lastrowid is None:
            raise RuntimeError("failed to create tool call log row")
        tool_call_id = cursor.lastrowid
        logger.info(
            "tool call started call_id=%s tool_call_id=%s tool_name=%s",
            call_id,
            tool_call_id,
            tool_name,
        )
        return tool_call_id


def finish_tool_call(db_path: Path, tool_call_id: int, status: str) -> None:
    if status not in VALID_FINAL_STATUSES:
        raise ValueError(f"invalid final tool status: {status}")

    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT tool_name FROM tool_calls WHERE id = ?", (tool_call_id,)).fetchone()
        cursor = conn.execute(
            """
            UPDATE tool_calls
            SET status = ?, finished_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'started'
            """,
            (status, tool_call_id),
        )
        conn.commit()
        if cursor.rowcount != 1 or row is None:
            raise ValueError(f"tool call log row not found or already finished: {tool_call_id}")
        logger.info(
            "tool call finished tool_call_id=%s tool_name=%s status=%s",
            tool_call_id,
            row[0],
            status,
        )
