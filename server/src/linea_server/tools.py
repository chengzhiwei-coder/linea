from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from inspect import signature
from typing import Any

ToolHandler = Callable[[dict[str, Any]], Awaitable[str]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    schema: dict[str, Any]
    handler: ToolHandler


DEFAULT_TIME_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "name": "get_current_time",
    "description": "Return the server local time as an ISO-8601 timestamp.",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}


def _default_schema(name: str) -> dict[str, Any]:
    return {
        "type": "function",
        "name": name,
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    }


def _normalize_handler(handler: Callable[..., Awaitable[str]]) -> ToolHandler:
    if len(signature(handler).parameters) == 0:
        async def no_argument_handler(arguments: dict[str, Any]) -> str:
            return await handler()

        return no_argument_handler
    return handler


@dataclass
class ToolRegistry:
    _tools: dict[str, ToolDefinition] = field(default_factory=dict)

    def register(self, name: str, handler: Callable[..., Awaitable[str]], schema: dict[str, Any] | None = None) -> None:
        if name in self._tools:
            raise ValueError(f"tool already registered: {name}")
        self._tools[name] = ToolDefinition(
            name=name,
            schema=schema or _default_schema(name),
            handler=_normalize_handler(handler),
        )

    async def call(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        try:
            tool = self._tools[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc
        return await tool.handler(arguments or {})

    def tool_schemas(self) -> list[dict[str, Any]]:
        return [tool.schema for tool in self._tools.values()]


async def get_current_time() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


async def _get_current_time_tool(arguments: dict[str, Any]) -> str:
    return await get_current_time()


def register_default_tools(registry: ToolRegistry) -> None:
    registry.register("get_current_time", _get_current_time_tool, schema=DEFAULT_TIME_TOOL_SCHEMA)
