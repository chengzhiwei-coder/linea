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
