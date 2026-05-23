from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

ToolHandler = Callable[[], Awaitable[str]]


@dataclass
class ToolRegistry:
    _handlers: dict[str, ToolHandler] = field(default_factory=dict)

    def register(self, name: str, handler: ToolHandler) -> None:
        if name in self._handlers:
            raise ValueError(f"tool already registered: {name}")
        self._handlers[name] = handler

    async def call(self, name: str) -> str:
        try:
            handler = self._handlers[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc
        return await handler()


async def get_current_time() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def register_default_tools(registry: ToolRegistry) -> None:
    registry.register("get_current_time", get_current_time)
