import pytest

from app.services.ai.tools.current_time import run_current_time
from app.services.ai.tools.registry import ToolContext, execute, tool_specs
from app.services.ai.tools.server_info import run_server_info


def test_tool_specs_includes_search_only_when_available():
    names = {s["function"]["name"] for s in tool_specs(has_search=True)}
    assert {"web_search", "server_info", "current_time"} <= names
    assert "web_search" not in {s["function"]["name"] for s in tool_specs(has_search=False)}


def test_server_info_kinds():
    snap = {"member_count": 7, "roles": ["Admin", "Mod"], "channels": ["general"]}
    assert "7" in run_server_info("member_count", snap)
    assert "Admin" in run_server_info("roles", snap)
    assert "general" in run_server_info("channels", snap)
    assert "member_count" in run_server_info("???", snap)


def test_current_time_format():
    from datetime import UTC, datetime

    s = run_current_time(now=datetime(2026, 5, 31, 9, 30, tzinfo=UTC))
    assert "2026-05-31" in s and "UTC" in s


@pytest.mark.asyncio
async def test_execute_dispatch_server_info():
    ctx = ToolContext(guild_snapshot={"member_count": 3, "roles": [], "channels": []})
    out = await execute("server_info", {"kind": "member_count"}, ctx)
    assert "3" in out


@pytest.mark.asyncio
async def test_execute_unknown_tool():
    ctx = ToolContext(guild_snapshot=None)
    assert "không tồn tại" in (await execute("nope", {}, ctx)).lower()


@pytest.mark.asyncio
async def test_web_search_no_key(monkeypatch):
    from app.services.ai.tools import web_search as ws

    monkeypatch.setattr(ws.settings, "TAVILY_API_KEY", "", raising=False)
    out = await ws.run_web_search("gì đó")
    assert "chưa cấu hình" in out.lower()


def test_tool_specs_includes_actions_when_enabled():
    names = {s["function"]["name"] for s in tool_specs(has_search=False, include_actions=True)}
    assert {"create_role", "ban", "toggle_plugin"} <= names
    assert "create_role" not in {
        s["function"]["name"] for s in tool_specs(has_search=False, include_actions=False)
    }


@pytest.mark.asyncio
async def test_execute_dispatches_action_to_stage():
    # name là action -> đi nhánh actions.stage; thiếu quyền -> trả chuỗi "cần quyền"
    ctx = ToolContext(commander_perms={})
    out = await execute("create_role", {"name": "X"}, ctx)
    assert "quyền" in out.lower()
