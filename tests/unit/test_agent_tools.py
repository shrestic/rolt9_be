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


def test_tool_specs_has_list_and_delete_tools():
    names = {s["function"]["name"] for s in tool_specs(has_search=False)}
    assert {"list_reminders", "cancel_reminder", "delete_poll"} <= names


async def _mk_reminders(db_session):
    """guild + 2 reminder của commander 42 (1 'chơi game', 1 'họp nhóm')."""
    import uuid as _uuid
    from datetime import UTC, datetime, timedelta

    from app.models.guild import Guild
    from app.repositories.reminder import ReminderRepository

    gid = _uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    await db_session.commit()
    repo = ReminderRepository(db_session)
    now = datetime.now(UTC)
    await repo.create(
        guild_id=gid,
        channel_id=1,
        creator_id=42,
        target_ids=[42],
        message="chơi game tối nay",
        remind_at=now + timedelta(hours=5),
    )
    await repo.create(
        guild_id=gid,
        channel_id=1,
        creator_id=42,
        target_ids=[42],
        message="họp nhóm sáng",
        remind_at=now + timedelta(days=2),
    )
    await db_session.commit()
    return gid, repo


@pytest.mark.asyncio
async def test_list_reminders_shows_all_mine(db_session):
    gid, repo = await _mk_reminders(db_session)
    ctx = ToolContext(reminder_repo=repo, guild_pk=gid, commander_id=42)
    out = await execute("list_reminders", {}, ctx)
    assert "chơi game tối nay" in out and "họp nhóm sáng" in out


@pytest.mark.asyncio
async def test_cancel_reminder_unique_query_deletes(db_session):
    gid, repo = await _mk_reminders(db_session)
    ctx = ToolContext(reminder_repo=repo, guild_pk=gid, commander_id=42)
    out = await execute("cancel_reminder", {"query": "họp"}, ctx)
    await db_session.commit()
    assert "đã huỷ nhắc" in out.lower()
    remaining = await repo.pending_for_guild(gid)
    assert len(remaining) == 1 and "chơi game" in remaining[0].message


@pytest.mark.asyncio
async def test_cancel_reminder_ambiguous_lists_without_deleting(db_session):
    # nhiều cái khớp (query rỗng) -> liệt kê hỏi lại, KHÔNG xoá nhầm
    gid, repo = await _mk_reminders(db_session)
    ctx = ToolContext(reminder_repo=repo, guild_pk=gid, commander_id=42)
    out = await execute("cancel_reminder", {}, ctx)
    await db_session.commit()
    assert "nói rõ hơn" in out.lower()
    assert len(await repo.pending_for_guild(gid)) == 2  # còn nguyên cả 2


@pytest.mark.asyncio
async def test_cancel_reminder_all_flag(db_session):
    gid, repo = await _mk_reminders(db_session)
    ctx = ToolContext(reminder_repo=repo, guild_pk=gid, commander_id=42)
    out = await execute("cancel_reminder", {"all": True}, ctx)
    await db_session.commit()
    assert "tất cả" in out.lower()
    assert await repo.pending_for_guild(gid) == []


@pytest.mark.asyncio
async def test_delete_poll_stages_pending():
    ctx = ToolContext()
    out = await execute("delete_poll", {}, ctx)
    assert "poll" in out.lower()
    assert ctx.pending and ctx.pending[0].kind == "delete_poll"


@pytest.mark.asyncio
async def test_cancel_reminder_by_time_query(db_session):
    # Xoá theo GIỜ: "7h tối" phải khớp lời nhắc lúc 19:00 VN (= 12:00 UTC)
    import uuid as _uuid
    from datetime import UTC, datetime

    from app.models.guild import Guild
    from app.repositories.reminder import ReminderRepository

    gid = _uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    await db_session.commit()
    repo = ReminderRepository(db_session)
    await repo.create(
        guild_id=gid,
        channel_id=1,
        creator_id=42,
        target_ids=[42],
        message="rủ chơi game",
        remind_at=datetime(2099, 6, 1, 12, 0, tzinfo=UTC),
    )
    await db_session.commit()
    ctx = ToolContext(reminder_repo=repo, guild_pk=gid, commander_id=42)
    out = await execute("cancel_reminder", {"query": "7h tối"}, ctx)
    await db_session.commit()
    assert "đã huỷ" in out.lower()
    assert await repo.pending_for_guild(gid) == []


def test_tool_specs_has_subscription_tools():
    names = {s["function"]["name"] for s in tool_specs(has_search=False)}
    assert {"subscribe", "unsubscribe", "list_subscriptions"} <= names


async def _guild_for_subs(db_session):
    import uuid as _uuid

    from app.models.guild import Guild

    gid = _uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    await db_session.commit()
    return gid


@pytest.mark.asyncio
async def test_execute_subscribe_writes_db(db_session):
    from app.repositories.subscription import SubscriptionRepository

    gid = await _guild_for_subs(db_session)
    repo = SubscriptionRepository(db_session)
    ctx = ToolContext(subscription_repo=repo, guild_pk=gid, channel_id=55, commander_id=42)
    out = await execute("subscribe", {"topic": "tin chứng khoán", "time": "8:00"}, ctx)
    await db_session.commit()
    assert "đăng ký" in out.lower()
    subs = await repo.active_for_creator(gid, 42)
    assert len(subs) == 1 and subs[0].topic == "tin chứng khoán"
    assert subs[0].hour == 8 and subs[0].channel_id == 55


@pytest.mark.asyncio
async def test_execute_unsubscribe_and_list(db_session):
    from app.repositories.subscription import SubscriptionRepository

    gid = await _guild_for_subs(db_session)
    repo = SubscriptionRepository(db_session)
    await repo.create(
        guild_id=gid, channel_id=1, creator_id=42, topic="chứng khoán", hour=8, minute=0
    )
    await repo.create(guild_id=gid, channel_id=1, creator_id=42, topic="giá vàng", hour=9, minute=0)
    await db_session.commit()
    ctx = ToolContext(subscription_repo=repo, guild_pk=gid, commander_id=42)

    listed = await execute("list_subscriptions", {}, ctx)
    assert "chứng khoán" in listed and "giá vàng" in listed

    # mơ hồ (không query, 2 cái) -> liệt kê hỏi lại, KHÔNG xoá
    ambiguous = await execute("unsubscribe", {}, ctx)
    await db_session.commit()
    assert "nói rõ" in ambiguous.lower()
    assert len(await repo.active_for_creator(gid, 42)) == 2

    # đúng 1 khớp -> huỷ
    out = await execute("unsubscribe", {"query": "vàng"}, ctx)
    await db_session.commit()
    assert "đã huỷ" in out.lower()
    remaining = await repo.active_for_creator(gid, 42)
    assert len(remaining) == 1 and remaining[0].topic == "chứng khoán"
