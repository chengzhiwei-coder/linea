from datetime import datetime

from linea_server.tools import ToolRegistry, get_current_time, register_default_tools


async def test_get_current_time_returns_iso_8601_local_time():
    result = await get_current_time()

    parsed = datetime.fromisoformat(result)
    assert parsed.tzinfo is not None


async def test_default_registry_contains_get_current_time():
    registry = ToolRegistry()
    register_default_tools(registry)

    result = await registry.call("get_current_time")

    datetime.fromisoformat(result)
