import asyncio
import json
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

RUN_HERMES_TASK_SCHEMA: dict[str, Any] = {
    "type": "function",
    "name": "run_hermes_task",
    "description": "Start a Hermes background task and deliver its final result to Telegram.",
    "parameters": {
        "type": "object",
        "properties": {"task": {"type": "string"}},
        "required": ["task"],
        "additionalProperties": False,
    },
}

GET_HERMES_STATUS_SCHEMA: dict[str, Any] = {
    "type": "function",
    "name": "get_hermes_status",
    "description": "Return a short voice-safe status sentence for the current Hermes task.",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}

CANCEL_HERMES_TASK_SCHEMA: dict[str, Any] = {
    "type": "function",
    "name": "cancel_hermes_task",
    "description": "Request cancellation of the active Hermes task; pass confirm=true to terminate it.",
    "parameters": {
        "type": "object",
        "properties": {"confirm": {"type": "boolean"}},
        "additionalProperties": False,
    },
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


def _json_tool_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _voice_safe_sentence(message: str, *, max_length: int = 160) -> str:
    normalized = " ".join(message.split()).strip()
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 1].rstrip() + "…"


def _short_status_message(result: dict[str, Any]) -> str:
    progress_summary = result.get("progress_summary") or result.get("last_phase")
    if isinstance(progress_summary, str) and progress_summary.strip():
        return _voice_safe_sentence(progress_summary)

    status = result.get("status")
    if status in {"running", "cancel_pending"}:
        return "Hermes is still running; no detailed progress signal is available yet."
    if status == "idle":
        return "Hermes is idle."
    if status == "completed":
        return "The latest Hermes job completed; the final result will be sent to Telegram."
    if status in {"failed", "failed_orphaned"}:
        return "The latest Hermes job failed; check local diagnostics if needed."
    if status == "cancelled":
        return "The latest Hermes job was cancelled."
    return f"Hermes job is {status}." if isinstance(status, str) else "Hermes status is unavailable."


def _discard_cancelled_handler_task_exception(task: asyncio.Task[dict[str, Any]]) -> None:
    if task.cancelled():
        return
    task.exception()


def register_default_tools(registry: ToolRegistry, hermes_job_manager: Any | None = None) -> None:
    registry.register("get_current_time", _get_current_time_tool, schema=DEFAULT_TIME_TOOL_SCHEMA)
    if hermes_job_manager is None:
        return

    async def run_hermes_task(arguments: dict[str, Any]) -> str:
        start_task = asyncio.create_task(hermes_job_manager.start_task(str(arguments["task"])))
        try:
            result = await asyncio.shield(start_task)
        except asyncio.CancelledError:
            start_task.add_done_callback(_discard_cancelled_handler_task_exception)
            raise
        job_id = result.get("job_id")
        if result.get("ok") is True:
            message = f"Hermes started job {job_id}. I’ll send the result to Telegram when it finishes."
        else:
            message = str(result.get("message") or "Hermes could not start the task.")
        return _json_tool_payload({"ok": result.get("ok") is True, "message": message, "job_id": job_id})

    async def get_hermes_status(arguments: dict[str, Any]) -> str:
        result = await hermes_job_manager.get_status()
        return _json_tool_payload(
            {
                "ok": result.get("ok") is True,
                "message": _short_status_message(result),
                "job_id": result.get("job_id"),
                "status": result.get("status"),
            }
        )

    async def cancel_hermes_task(arguments: dict[str, Any]) -> str:
        if arguments.get("confirm") is True:
            result = await hermes_job_manager.confirm_cancel()
        else:
            result = await hermes_job_manager.request_cancel()
        return _json_tool_payload(
            {
                "ok": result.get("ok") is True,
                "message": str(result.get("message") or "Hermes cancellation status is unavailable."),
                "job_id": result.get("job_id"),
                "status": result.get("status"),
            }
        )

    registry.register("run_hermes_task", run_hermes_task, schema=RUN_HERMES_TASK_SCHEMA)
    registry.register("get_hermes_status", get_hermes_status, schema=GET_HERMES_STATUS_SCHEMA)
    registry.register("cancel_hermes_task", cancel_hermes_task, schema=CANCEL_HERMES_TASK_SCHEMA)
