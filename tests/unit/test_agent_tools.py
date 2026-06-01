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


def test_tool_specs_always_has_remember():
    assert "remember" in {s["function"]["name"] for s in tool_specs(has_search=False)}
    assert "remember" in {
        s["function"]["name"] for s in tool_specs(has_search=True, include_actions=True)
    }


@pytest.mark.asyncio
async def test_execute_remember_writes_doc(db_session):
    import uuid as _uuid

    from app.models.guild import Guild
    from app.repositories.memory_doc import MemoryDocRepository

    gid = _uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    await db_session.commit()
    ctx = ToolContext(memory_repo_doc=MemoryDocRepository(db_session), guild_pk=gid)
    out = await execute("remember", {"note": "gọi An là thằng loz"}, ctx)
    await db_session.commit()
    assert "ghi nhớ" in out.lower()
    assert "An" in await MemoryDocRepository(db_session).get_doc(gid)


@pytest.mark.asyncio
async def test_execute_remember_no_ctx():
    out = await execute("remember", {"note": "x"}, ToolContext())
    assert "chưa ghi" in out.lower()


def test_tool_specs_always_has_create_poll():
    assert "create_poll" in {s["function"]["name"] for s in tool_specs(has_search=False)}


@pytest.mark.asyncio
async def test_execute_create_poll_stages_pending():
    ctx = ToolContext()
    out = await execute(
        "create_poll",
        {"question": "Tối nay ăn gì?", "options": ["Phở", "Cơm tấm", "Bún bò"]},
        ctx,
    )
    assert "poll" in out.lower()
    assert len(ctx.pending) == 1
    p = ctx.pending[0]
    assert p.kind == "create_poll" and p.destructive is False
    assert p.params["options"] == ["Phở", "Cơm tấm", "Bún bò"]
    assert p.params["duration_hours"] == 24  # mặc định


@pytest.mark.asyncio
async def test_execute_create_poll_rejects_too_few_options():
    ctx = ToolContext()
    out = await execute("create_poll", {"question": "?", "options": ["chỉ 1"]}, ctx)
    assert "2-10" in out and not ctx.pending


def test_tool_specs_always_has_remind():
    assert "remind" in {s["function"]["name"] for s in tool_specs(has_search=False)}


@pytest.mark.asyncio
async def test_execute_remind_writes_db(db_session):
    import uuid as _uuid
    from datetime import UTC, datetime, timedelta
    from zoneinfo import ZoneInfo

    from app.models.guild import Guild
    from app.repositories.reminder import ReminderRepository

    gid = _uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    await db_session.commit()

    # "when" giờ VN, trong tương lai
    when = (datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")) + timedelta(days=1)).strftime(
        "%Y-%m-%d %H:%M"
    )
    ctx = ToolContext(
        reminder_repo=ReminderRepository(db_session),
        guild_pk=gid,
        channel_id=555,
        commander_id=42,
        target_user_ids=[42, 77],
    )
    out = await execute("remind", {"when": when, "message": "chơi game"}, ctx)
    await db_session.commit()
    assert "đặt nhắc" in out.lower()
    pending = await ReminderRepository(db_session).due(datetime.now(UTC) + timedelta(days=2))
    assert len(pending) == 1
    assert pending[0].target_ids == [42, 77] and pending[0].channel_id == 555


@pytest.mark.asyncio
async def test_execute_remind_rejects_past():
    ctx = ToolContext(reminder_repo=object(), guild_pk="x", channel_id=1, commander_id=1)
    out = await execute("remind", {"when": "2000-01-01 00:00", "message": "trễ"}, ctx)
    assert "qua" in out.lower()


@pytest.mark.asyncio
async def test_execute_remind_no_ctx():
    out = await execute("remind", {"when": "2099-01-01 00:00", "message": "x"}, ToolContext())
    assert "chưa đặt được" in out.lower()
