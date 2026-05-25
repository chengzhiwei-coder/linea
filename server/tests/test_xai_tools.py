import asyncio
import json
import sqlite3
from typing import Any

import pytest

from linea_server.db import initialize_db
from linea_server.tools import ToolRegistry, register_default_tools
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


class FakeHermesJobManager:
    def __init__(self) -> None:
        self.started_tasks: list[str] = []
        self.cancel_requested = False
        self.cancel_confirmed = False

    async def start_task(self, task: str) -> dict[str, Any]:
        self.started_tasks.append(task)
        return {"ok": True, "status": "running", "job_id": "job-123", "message": "Hermes job started"}

    async def get_status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "running",
            "job_id": "job-123",
            "progress_summary": "Hermes is checking Linea status.",
        }

    async def request_cancel(self) -> dict[str, Any]:
        self.cancel_requested = True
        return {
            "ok": True,
            "status": "cancel_pending",
            "job_id": "job-123",
            "message": "Please confirm cancellation before I terminate Hermes.",
        }

    async def confirm_cancel(self) -> dict[str, Any]:
        self.cancel_confirmed = True
        return {
            "ok": True,
            "status": "cancel_pending",
            "job_id": "job-123",
            "message": "Hermes job termination requested.",
        }


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


async def test_xai_run_hermes_task_function_call_returns_ack_without_waiting_for_final_completion(tmp_path):
    db_path = tmp_path / "linea.db"
    initialize_db(db_path)
    manager = FakeHermesJobManager()
    registry = ToolRegistry()
    register_default_tools(registry, hermes_job_manager=manager)
    connection = FakeRealtimeConnection(
        [
            {
                "type": "response.function_call_arguments.done",
                "name": "run_hermes_task",
                "call_id": "call-run",
                "arguments": '{"task":"check Linea status"}',
            }
        ]
    )
    bridge = XaiRealtimeBridge(
        XaiConfig(api_key="secret"),
        connection=connection,
        db_path=db_path,
        tool_registry=registry,
        is_tool_call_active=lambda call_id: call_id == "call-run",
    )

    await bridge.process_events()

    assert manager.started_tasks == ["check Linea status"]
    output = json.loads(connection.sent[-2]["item"]["output"])
    assert output == {
        "ok": True,
        "message": "Hermes started job job-123. I’ll send the result to Telegram when it finishes.",
        "job_id": "job-123",
    }
    assert connection.sent[-1] == {"type": "response.create"}
    assert fetch_tool_rows(db_path)[0][:3] == ("call-run", "run_hermes_task", "success")


async def test_xai_get_hermes_status_function_call_returns_short_progress_sentence(tmp_path):
    db_path = tmp_path / "linea.db"
    initialize_db(db_path)
    manager = FakeHermesJobManager()
    registry = ToolRegistry()
    register_default_tools(registry, hermes_job_manager=manager)
    connection = FakeRealtimeConnection(
        [
            {
                "type": "response.function_call_arguments.done",
                "name": "get_hermes_status",
                "call_id": "call-status",
                "arguments": "{}",
            }
        ]
    )
    bridge = XaiRealtimeBridge(
        XaiConfig(api_key="secret"),
        connection=connection,
        db_path=db_path,
        tool_registry=registry,
        is_tool_call_active=lambda call_id: call_id == "call-status",
    )

    await bridge.process_events()

    output = json.loads(connection.sent[-2]["item"]["output"])
    assert output == {
        "ok": True,
        "message": "Hermes is checking Linea status.",
        "job_id": "job-123",
        "status": "running",
    }
    assert fetch_tool_rows(db_path)[0][:3] == ("call-status", "get_hermes_status", "success")


async def test_xai_cancel_hermes_task_without_confirm_asks_for_confirmation(tmp_path):
    db_path = tmp_path / "linea.db"
    initialize_db(db_path)
    manager = FakeHermesJobManager()
    registry = ToolRegistry()
    register_default_tools(registry, hermes_job_manager=manager)
    connection = FakeRealtimeConnection(
        [
            {
                "type": "response.function_call_arguments.done",
                "name": "cancel_hermes_task",
                "call_id": "call-cancel-request",
                "arguments": "{}",
            }
        ]
    )
    bridge = XaiRealtimeBridge(
        XaiConfig(api_key="secret"),
        connection=connection,
        db_path=db_path,
        tool_registry=registry,
        is_tool_call_active=lambda call_id: call_id == "call-cancel-request",
    )

    await bridge.process_events()

    output = json.loads(connection.sent[-2]["item"]["output"])
    assert output == {
        "ok": True,
        "message": "Please confirm cancellation before I terminate Hermes.",
        "job_id": "job-123",
        "status": "cancel_pending",
    }
    assert manager.cancel_requested is True
    assert manager.cancel_confirmed is False
    assert fetch_tool_rows(db_path)[0][:3] == ("call-cancel-request", "cancel_hermes_task", "success")


async def test_xai_cancel_hermes_task_with_confirm_cancels_active_job(tmp_path):
    db_path = tmp_path / "linea.db"
    initialize_db(db_path)
    manager = FakeHermesJobManager()
    registry = ToolRegistry()
    register_default_tools(registry, hermes_job_manager=manager)
    connection = FakeRealtimeConnection(
        [
            {
                "type": "response.function_call_arguments.done",
                "name": "cancel_hermes_task",
                "call_id": "call-cancel-confirm",
                "arguments": '{"confirm":true}',
            }
        ]
    )
    bridge = XaiRealtimeBridge(
        XaiConfig(api_key="secret"),
        connection=connection,
        db_path=db_path,
        tool_registry=registry,
        is_tool_call_active=lambda call_id: call_id == "call-cancel-confirm",
    )

    await bridge.process_events()

    output = json.loads(connection.sent[-2]["item"]["output"])
    assert output == {
        "ok": True,
        "message": "Hermes job termination requested.",
        "job_id": "job-123",
        "status": "cancel_pending",
    }
    assert manager.cancel_requested is False
    assert manager.cancel_confirmed is True
    assert fetch_tool_rows(db_path)[0][:3] == ("call-cancel-confirm", "cancel_hermes_task", "success")


async def test_xai_tool_call_log_records_started_status_while_handler_is_running(tmp_path):
    db_path = tmp_path / "linea.db"
    initialize_db(db_path)
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_tool(arguments):
        started.set()
        await release.wait()
        return "done"

    registry = ToolRegistry()
    registry.register("slow_tool", slow_tool)
    connection = FakeRealtimeConnection(
        [
            {
                "type": "response.function_call_arguments.done",
                "name": "slow_tool",
                "call_id": "call-started",
                "arguments": "{}",
            }
        ]
    )
    bridge = XaiRealtimeBridge(
        XaiConfig(api_key="secret"),
        connection=connection,
        db_path=db_path,
        tool_registry=registry,
        is_tool_call_active=lambda call_id: call_id == "call-started",
    )

    process_task = asyncio.create_task(bridge.process_events())
    await started.wait()

    assert fetch_tool_rows(db_path)[0][:3] == ("call-started", "slow_tool", "started")

    release.set()
    await process_task
    assert fetch_tool_rows(db_path)[0][:3] == ("call-started", "slow_tool", "success")


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
