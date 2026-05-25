import asyncio
import sqlite3

import pytest

from linea_server.db import initialize_db
from linea_server.tools import ToolRegistry
from linea_server.xai_config import XaiConfig
from linea_server.xai_realtime import XaiRealtimeBridge


class FakeRealtimeConnection:
    def __init__(self, incoming_events):
        self.incoming_events = list(incoming_events)
        self.sent = []
        self.closed = False

    async def send_json(self, payload):
        self.sent.append(payload)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.incoming_events:
            raise StopAsyncIteration
        return self.incoming_events.pop(0)

    async def close(self):
        self.closed = True


def fetch_tool_rows(db_path):
    with sqlite3.connect(db_path) as conn:
        return conn.execute(
            "SELECT call_id, tool_name, status, finished_at FROM tool_calls ORDER BY id"
        ).fetchall()


async def test_xai_get_current_time_tool_call_logs_executes_and_sends_result_when_active(tmp_path):
    db_path = tmp_path / "linea.db"
    initialize_db(db_path)
    executed = False

    async def fake_time():
        nonlocal executed
        executed = True
        return "2026-05-23T12:34:56+00:00"

    registry = ToolRegistry()
    registry.register("get_current_time", fake_time)
    connection = FakeRealtimeConnection(
        [
            {
                "type": "response.function_call_arguments.done",
                "name": "get_current_time",
                "call_id": "call-1",
                "arguments": "{}",
            }
        ]
    )
    bridge = XaiRealtimeBridge(
        XaiConfig(api_key="secret"),
        connection=connection,
        db_path=db_path,
        tool_registry=registry,
        is_tool_call_active=lambda call_id: call_id == "call-1",
    )

    await bridge.process_events()

    assert executed is True
    rows = fetch_tool_rows(db_path)
    assert rows[0][:3] == ("call-1", "get_current_time", "success")
    assert rows[0][3] is not None
    assert connection.sent[-2:] == [
        {
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": "call-1",
                "output": "2026-05-23T12:34:56+00:00",
            },
        },
        {"type": "response.create"},
    ]


async def test_xai_tool_result_is_not_sent_when_call_is_no_longer_active(tmp_path):
    db_path = tmp_path / "linea.db"
    initialize_db(db_path)

    async def fake_time():
        return "2026-05-23T12:34:56+00:00"

    registry = ToolRegistry()
    registry.register("get_current_time", fake_time)
    connection = FakeRealtimeConnection(
        [
            {
                "type": "response.function_call_arguments.done",
                "name": "get_current_time",
                "call_id": "call-1",
                "arguments": {},
            }
        ]
    )
    bridge = XaiRealtimeBridge(
        XaiConfig(api_key="secret"),
        connection=connection,
        db_path=db_path,
        tool_registry=registry,
        is_tool_call_active=lambda call_id: False,
    )

    await bridge.process_events()

    rows = fetch_tool_rows(db_path)
    assert rows[0][:3] == ("call-1", "get_current_time", "success")
    assert rows[0][3] is not None
    assert [payload["type"] for payload in connection.sent] == ["session.update"]


async def test_xai_tool_result_is_not_sent_without_explicit_active_call_predicate(tmp_path):
    db_path = tmp_path / "linea.db"
    initialize_db(db_path)

    async def fake_time():
        return "2026-05-23T12:34:56+00:00"

    registry = ToolRegistry()
    registry.register("get_current_time", fake_time)
    connection = FakeRealtimeConnection(
        [
            {
                "type": "response.function_call_arguments.done",
                "name": "get_current_time",
                "call_id": "call-1",
                "arguments": {},
            }
        ]
    )
    bridge = XaiRealtimeBridge(
        XaiConfig(api_key="secret"),
        connection=connection,
        db_path=db_path,
        tool_registry=registry,
    )

    await bridge.process_events()

    rows = fetch_tool_rows(db_path)
    assert rows[0][:3] == ("call-1", "get_current_time", "success")
    assert rows[0][3] is not None
    assert [payload["type"] for payload in connection.sent] == ["session.update"]


async def test_xai_tool_call_logs_error_when_tool_raises(tmp_path):
    db_path = tmp_path / "linea.db"
    initialize_db(db_path)

    async def broken_time():
        raise RuntimeError("clock broke")

    registry = ToolRegistry()
    registry.register("get_current_time", broken_time)
    connection = FakeRealtimeConnection(
        [
            {
                "type": "response.function_call_arguments.done",
                "name": "get_current_time",
                "call_id": "call-1",
                "arguments": "{}",
            }
        ]
    )
    bridge = XaiRealtimeBridge(
        XaiConfig(api_key="secret"),
        connection=connection,
        db_path=db_path,
        tool_registry=registry,
    )

    await bridge.process_events()

    rows = fetch_tool_rows(db_path)
    assert rows[0][:3] == ("call-1", "get_current_time", "error")
    assert rows[0][3] is not None
    assert [payload["type"] for payload in connection.sent] == ["session.update"]


async def test_xai_tool_call_logs_cancelled_when_shutdown_cancels_tool(tmp_path):
    db_path = tmp_path / "linea.db"
    initialize_db(db_path)

    async def cancelled_time():
        raise asyncio.CancelledError

    registry = ToolRegistry()
    registry.register("get_current_time", cancelled_time)
    connection = FakeRealtimeConnection(
        [
            {
                "type": "response.function_call_arguments.done",
                "name": "get_current_time",
                "call_id": "call-1",
                "arguments": "{}",
            }
        ]
    )
    bridge = XaiRealtimeBridge(
        XaiConfig(api_key="secret"),
        connection=connection,
        db_path=db_path,
        tool_registry=registry,
    )

    with pytest.raises(asyncio.CancelledError):
        await bridge.process_events()

    rows = fetch_tool_rows(db_path)
    assert rows[0][:3] == ("call-1", "get_current_time", "cancelled")
    assert rows[0][3] is not None
    assert [payload["type"] for payload in connection.sent] == ["session.update"]


async def test_xai_tool_call_passes_parsed_arguments_to_registry_handler(tmp_path):
    db_path = tmp_path / "linea.db"
    initialize_db(db_path)
    received_arguments = None

    async def fake_hermes(arguments):
        nonlocal received_arguments
        received_arguments = arguments
        return "started"

    registry = ToolRegistry()
    registry.register("run_hermes", fake_hermes)
    connection = FakeRealtimeConnection(
        [
            {
                "type": "response.function_call_arguments.done",
                "name": "run_hermes",
                "call_id": "call-1",
                "arguments": '{"task":"write a note"}',
            }
        ]
    )
    bridge = XaiRealtimeBridge(
        XaiConfig(api_key="secret"),
        connection=connection,
        db_path=db_path,
        tool_registry=registry,
        is_tool_call_active=lambda call_id: call_id == "call-1",
    )

    await bridge.process_events()

    assert received_arguments == {"task": "write a note"}
    rows = fetch_tool_rows(db_path)
    assert rows[0][:3] == ("call-1", "run_hermes", "success")
    assert connection.sent[-2]["item"]["output"] == "started"


async def test_xai_tool_call_sends_error_output_for_invalid_json_arguments(tmp_path):
    db_path = tmp_path / "linea.db"
    initialize_db(db_path)
    executed = False

    async def fake_hermes(arguments):
        nonlocal executed
        executed = True
        return "started"

    registry = ToolRegistry()
    registry.register("run_hermes", fake_hermes)
    connection = FakeRealtimeConnection(
        [
            {
                "type": "response.function_call_arguments.done",
                "name": "run_hermes",
                "call_id": "call-1",
                "arguments": "{not json}",
            }
        ]
    )
    bridge = XaiRealtimeBridge(
        XaiConfig(api_key="secret"),
        connection=connection,
        db_path=db_path,
        tool_registry=registry,
        is_tool_call_active=lambda call_id: call_id == "call-1",
    )

    await bridge.process_events()

    assert executed is False
    rows = fetch_tool_rows(db_path)
    assert rows[0][:3] == ("call-1", "run_hermes", "error")
    assert connection.sent[-2:] == [
        {
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": "call-1",
                "output": '{"ok": false, "error": "invalid tool arguments"}',
            },
        },
        {"type": "response.create"},
    ]


async def test_bridge_advertises_tool_schemas_from_registry():
    schema = {
        "type": "function",
        "name": "run_hermes",
        "parameters": {
            "type": "object",
            "properties": {"task": {"type": "string"}},
            "required": ["task"],
            "additionalProperties": False,
        },
    }

    async def fake_hermes(arguments):
        return "started"

    registry = ToolRegistry()
    registry.register("run_hermes", fake_hermes, schema=schema)
    connection = FakeRealtimeConnection([])
    bridge = XaiRealtimeBridge(
        XaiConfig(api_key="secret"),
        connection=connection,
        tool_registry=registry,
    )

    await bridge.start()

    assert connection.sent[0]["session"]["tools"] == [schema]
