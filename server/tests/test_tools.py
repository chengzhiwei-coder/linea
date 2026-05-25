import json
from datetime import datetime
from typing import Any

import pytest

from linea_server.tools import ToolRegistry, get_current_time, register_default_tools


async def test_get_current_time_returns_iso_8601_local_time():
    result = await get_current_time()

    parsed = datetime.fromisoformat(result)
    assert parsed.tzinfo is not None


async def test_registered_tool_receives_structured_arguments_and_exposes_schema():
    registry = ToolRegistry()
    received_arguments: dict[str, Any] | None = None
    schema = {
        "type": "function",
        "name": "echo_task",
        "description": "Echo a structured task.",
        "parameters": {
            "type": "object",
            "properties": {"task": {"type": "string"}},
            "required": ["task"],
            "additionalProperties": False,
        },
    }

    async def echo_task(arguments: dict[str, Any]) -> str:
        nonlocal received_arguments
        received_arguments = arguments
        return str(arguments["task"])

    registry.register("echo_task", echo_task, schema=schema)

    result = await registry.call("echo_task", {"task": "summarize"})

    assert result == "summarize"
    assert received_arguments == {"task": "summarize"}
    assert registry.tool_schemas() == [schema]


async def test_default_registry_contains_get_current_time_and_allows_no_argument_call():
    registry = ToolRegistry()
    register_default_tools(registry)

    result = await registry.call("get_current_time")

    datetime.fromisoformat(result)
    assert registry.tool_schemas() == [
        {
            "type": "function",
            "name": "get_current_time",
            "description": "Return the server local time as an ISO-8601 timestamp.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        }
    ]


class FakeHermesJobManager:
    def __init__(self, status_result: dict[str, Any] | None = None) -> None:
        self.started_tasks: list[str] = []
        self.cancel_requested = False
        self.cancel_confirmed = False
        self._status_result = status_result or {
            "ok": True,
            "status": "running",
            "job_id": "job-123",
            "progress_summary": "Checking the database schema.",
            "message": "Checking the database schema.",
        }

    async def start_task(self, task: str) -> dict[str, Any]:
        self.started_tasks.append(task)
        return {"ok": True, "status": "running", "job_id": "job-123", "message": "Hermes job started"}

    async def get_status(self) -> dict[str, Any]:
        return self._status_result

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


async def test_default_registry_with_hermes_manager_exposes_strict_hermes_tool_schemas():
    registry = ToolRegistry()
    register_default_tools(registry, hermes_job_manager=FakeHermesJobManager())

    schemas_by_name = {schema["name"]: schema for schema in registry.tool_schemas()}

    assert set(schemas_by_name) == {
        "get_current_time",
        "run_hermes_task",
        "get_hermes_status",
        "cancel_hermes_task",
    }
    assert schemas_by_name["run_hermes_task"]["parameters"] == {
        "type": "object",
        "properties": {"task": {"type": "string"}},
        "required": ["task"],
        "additionalProperties": False,
    }
    assert schemas_by_name["get_hermes_status"]["parameters"] == {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    assert schemas_by_name["cancel_hermes_task"]["parameters"] == {
        "type": "object",
        "properties": {"confirm": {"type": "boolean"}},
        "additionalProperties": False,
    }


async def test_run_hermes_task_returns_acknowledgement_json_not_final_result():
    manager = FakeHermesJobManager()
    registry = ToolRegistry()
    register_default_tools(registry, hermes_job_manager=manager)

    payload = json.loads(await registry.call("run_hermes_task", {"task": "Write a note"}))

    assert manager.started_tasks == ["Write a note"]
    assert payload == {
        "ok": True,
        "message": "Hermes started job job-123. I’ll send the result to Telegram when it finishes.",
        "job_id": "job-123",
    }


async def test_get_hermes_status_returns_one_short_sentence_in_json_payload():
    registry = ToolRegistry()
    register_default_tools(registry, hermes_job_manager=FakeHermesJobManager())

    payload = json.loads(await registry.call("get_hermes_status"))

    assert payload == {"ok": True, "message": "Checking the database schema.", "job_id": "job-123", "status": "running"}
    assert payload["message"].count(".") == 1


async def test_get_hermes_status_does_not_speak_raw_final_output():
    registry = ToolRegistry()
    manager = FakeHermesJobManager(
        {
            "ok": True,
            "status": "completed",
            "job_id": "job-123",
            "progress_summary": None,
            "message": "raw stdout line one\nraw stdout line two with details",
        }
    )
    register_default_tools(registry, hermes_job_manager=manager)

    payload = json.loads(await registry.call("get_hermes_status"))

    assert payload == {
        "ok": True,
        "message": "The latest Hermes job completed; the final result will be sent to Telegram.",
        "job_id": "job-123",
        "status": "completed",
    }


async def test_cancel_hermes_task_requires_confirmation_before_terminating():
    manager = FakeHermesJobManager()
    registry = ToolRegistry()
    register_default_tools(registry, hermes_job_manager=manager)

    first_payload = json.loads(await registry.call("cancel_hermes_task"))
    second_payload = json.loads(await registry.call("cancel_hermes_task", {"confirm": True}))

    assert first_payload == {
        "ok": True,
        "message": "Please confirm cancellation before I terminate Hermes.",
        "job_id": "job-123",
        "status": "cancel_pending",
    }
    assert manager.cancel_requested is True
    assert manager.cancel_confirmed is True
    assert second_payload == {
        "ok": True,
        "message": "Hermes job termination requested.",
        "job_id": "job-123",
        "status": "cancel_pending",
    }


async def test_duplicate_tool_names_raise_value_error():
    registry = ToolRegistry()

    async def first_tool(arguments: dict[str, Any]) -> str:
        return "first"

    async def second_tool(arguments: dict[str, Any]) -> str:
        return "second"

    registry.register("duplicate", first_tool)

    with pytest.raises(ValueError, match="tool already registered: duplicate"):
        registry.register("duplicate", second_tool)


async def test_unknown_tools_raise_key_error():
    registry = ToolRegistry()

    with pytest.raises(KeyError, match="unknown tool: missing"):
        await registry.call("missing")
