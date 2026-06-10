import pytest

from app.services.ai.tools.current_time import run_current_time
from app.services.ai.tools.registry import ToolContext, execute, tool_specs
from app.services.ai.tools.server_info import run_server_info


def test_tool_specs_includes_search_only_when_available():
    names = {s["function"]["name"] for s in tool_specs(has_search=True)}
    assert {"web_search", "server_info", "current_time"} <= names
    assert "web_search" not in {s["function"]["name"] for s in tool_specs(has_search=False)}


def test_tool_specs_includes_read_link_with_search():
    names = {s["function"]["name"] for s in tool_specs(has_search=True)}
    assert "read_link" in names
    assert "read_link" not in {s["function"]["name"] for s in tool_specs(has_search=False)}


@pytest.mark.asyncio
async def test_execute_dispatches_read_link(monkeypatch):
    import app.services.ai.tools.registry as reg

    called = {}

    async def fake_read(url):
        called["url"] = url
        return "CONTENT READ"

    monkeypatch.setattr(reg, "run_read_link", fake_read)
    out = await execute("read_link", {"url": "https://x.com/bai"}, ToolContext())
    assert out == "CONTENT READ" and called["url"] == "https://x.com/bai"


def test_remind_and_subscribe_carry_ambiguous_time_rule():
    # remind + subscribe must both warn about AMBIGUOUS morning/afternoon times (ask back when 1-12 is unclear).
    specs = {
        s["function"]["name"]: s["function"]["description"] for s in tool_specs(has_search=True)
    }
    for name in ("remind", "subscribe"):
        assert "AMBIGUOUS" in specs[name] and "am or pm" in specs[name]


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
    assert "doesn't exist" in (await execute("nope", {}, ctx)).lower()


@pytest.mark.asyncio
async def test_web_search_no_key(monkeypatch):
    from app.services.ai.tools import web_search as ws

    monkeypatch.setattr(ws.settings, "TAVILY_API_KEY", "", raising=False)
    out = await ws.run_web_search("something")
    assert "not configured" in out.lower()


def test_tool_specs_includes_actions_when_enabled():
    names = {s["function"]["name"] for s in tool_specs(has_search=False, include_actions=True)}
    assert {"create_role", "ban", "toggle_plugin"} <= names
    assert "create_role" not in {
        s["function"]["name"] for s in tool_specs(has_search=False, include_actions=False)
    }


@pytest.mark.asyncio
async def test_execute_dispatches_action_to_stage():
    # name is an action -> goes down the actions.stage branch; missing perm -> returns a "need permission" string
    ctx = ToolContext(commander_perms={})
    out = await execute("create_role", {"name": "X"}, ctx)
    assert "permission" in out.lower()


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
    out = await execute("remember", {"note": "call An a jerk"}, ctx)
    await db_session.commit()
    assert "noted" in out.lower()
    assert "An" in await MemoryDocRepository(db_session).get_doc(gid)


@pytest.mark.asyncio
async def test_execute_remember_no_ctx():
    out = await execute("remember", {"note": "x"}, ToolContext())
    assert "couldn't remember" in out.lower()


def test_tool_specs_always_has_create_poll():
    assert "create_poll" in {s["function"]["name"] for s in tool_specs(has_search=False)}


@pytest.mark.asyncio
async def test_execute_create_poll_stages_pending():
    ctx = ToolContext()
    out = await execute(
        "create_poll",
        {
            "question": "What's for dinner tonight?",
            "options": ["Pho", "Broken rice", "Beef noodles"],
        },
        ctx,
    )
    assert "poll" in out.lower()
    assert len(ctx.pending) == 1
    p = ctx.pending[0]
    assert p.kind == "create_poll" and p.destructive is False
    assert p.params["options"] == ["Pho", "Broken rice", "Beef noodles"]
    assert p.params["duration_hours"] == 24  # default


@pytest.mark.asyncio
async def test_execute_create_poll_rejects_too_few_options():
    ctx = ToolContext()
    out = await execute("create_poll", {"question": "?", "options": ["only 1"]}, ctx)
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

    # "when" in VN time, in the future
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
    out = await execute("remind", {"when": when, "message": "play games"}, ctx)
    await db_session.commit()
    assert "reminder set" in out.lower()
    pending = await ReminderRepository(db_session).due(datetime.now(UTC) + timedelta(days=2))
    assert len(pending) == 1
    assert pending[0].target_ids == [42, 77] and pending[0].channel_id == 555


@pytest.mark.asyncio
async def test_execute_remind_rejects_past():
    ctx = ToolContext(reminder_repo=object(), guild_pk="x", channel_id=1, commander_id=1)
    out = await execute("remind", {"when": "2000-01-01 00:00", "message": "late"}, ctx)
    assert "passed" in out.lower()


@pytest.mark.asyncio
async def test_execute_remind_no_ctx():
    out = await execute("remind", {"when": "2099-01-01 00:00", "message": "x"}, ToolContext())
    assert "can't set" in out.lower()


def test_tool_specs_has_list_and_delete_tools():
    names = {s["function"]["name"] for s in tool_specs(has_search=False)}
    assert {"list_reminders", "cancel_reminder", "delete_poll"} <= names


async def _mk_reminders(db_session):
    """guild + 2 reminders for commander 42 (1 'play games', 1 'team meeting')."""
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
        message="play games tonight",
        remind_at=now + timedelta(hours=5),
    )
    await repo.create(
        guild_id=gid,
        channel_id=1,
        creator_id=42,
        target_ids=[42],
        message="team meeting in the morning",
        remind_at=now + timedelta(days=2),
    )
    await db_session.commit()
    return gid, repo


@pytest.mark.asyncio
async def test_list_reminders_shows_all_mine(db_session):
    gid, repo = await _mk_reminders(db_session)
    ctx = ToolContext(reminder_repo=repo, guild_pk=gid, commander_id=42)
    out = await execute("list_reminders", {}, ctx)
    assert "play games tonight" in out and "team meeting in the morning" in out


@pytest.mark.asyncio
async def test_cancel_reminder_unique_query_deletes(db_session):
    gid, repo = await _mk_reminders(db_session)
    ctx = ToolContext(reminder_repo=repo, guild_pk=gid, commander_id=42)
    out = await execute("cancel_reminder", {"query": "meeting"}, ctx)
    await db_session.commit()
    assert "cancelled reminder" in out.lower()
    remaining = await repo.pending_for_guild(gid)
    assert len(remaining) == 1 and "play games" in remaining[0].message


@pytest.mark.asyncio
async def test_cancel_reminder_ambiguous_lists_without_deleting(db_session):
    # multiple match (empty query) -> list and ask back, DON'T delete the wrong one
    gid, repo = await _mk_reminders(db_session)
    ctx = ToolContext(reminder_repo=repo, guild_pk=gid, commander_id=42)
    out = await execute("cancel_reminder", {}, ctx)
    await db_session.commit()
    assert "be more specific" in out.lower()
    assert len(await repo.pending_for_guild(gid)) == 2  # both still intact


@pytest.mark.asyncio
async def test_cancel_reminder_all_flag(db_session):
    gid, repo = await _mk_reminders(db_session)
    ctx = ToolContext(reminder_repo=repo, guild_pk=gid, commander_id=42)
    out = await execute("cancel_reminder", {"all": True}, ctx)
    await db_session.commit()
    assert "all" in out.lower()
    assert await repo.pending_for_guild(gid) == []


@pytest.mark.asyncio
async def test_delete_poll_stages_pending():
    ctx = ToolContext()
    out = await execute("delete_poll", {}, ctx)
    assert "poll" in out.lower()
    assert ctx.pending and ctx.pending[0].kind == "delete_poll"


@pytest.mark.asyncio
async def test_cancel_reminder_by_time_query(db_session):
    # Cancel by TIME: "7pm" must match the reminder at 19:00 VN (= 12:00 UTC)
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
        message="invite to play games",
        remind_at=datetime(2099, 6, 1, 12, 0, tzinfo=UTC),
    )
    await db_session.commit()
    ctx = ToolContext(reminder_repo=repo, guild_pk=gid, commander_id=42)
    out = await execute("cancel_reminder", {"query": "7pm"}, ctx)
    await db_session.commit()
    assert "cancelled" in out.lower()
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
    out = await execute("subscribe", {"topic": "stock market news", "time": "8:00"}, ctx)
    await db_session.commit()
    assert "subscribed" in out.lower()
    subs = await repo.active_for_creator(gid, 42)
    assert len(subs) == 1 and subs[0].topic == "stock market news"
    assert subs[0].hour == 8 and subs[0].channel_id == 55


@pytest.mark.asyncio
async def test_execute_unsubscribe_and_list(db_session):
    from app.repositories.subscription import SubscriptionRepository

    gid = await _guild_for_subs(db_session)
    repo = SubscriptionRepository(db_session)
    await repo.create(guild_id=gid, channel_id=1, creator_id=42, topic="stocks", hour=8, minute=0)
    await repo.create(
        guild_id=gid, channel_id=1, creator_id=42, topic="gold price", hour=9, minute=0
    )
    await db_session.commit()
    ctx = ToolContext(subscription_repo=repo, guild_pk=gid, commander_id=42)

    listed = await execute("list_subscriptions", {}, ctx)
    assert "stocks" in listed and "gold price" in listed

    # ambiguous (no query, 2 of them) -> list and ask back, DON'T delete
    ambiguous = await execute("unsubscribe", {}, ctx)
    await db_session.commit()
    assert "say which one" in ambiguous.lower()
    assert len(await repo.active_for_creator(gid, 42)) == 2

    # exactly 1 match -> cancel
    out = await execute("unsubscribe", {"query": "gold"}, ctx)
    await db_session.commit()
    assert "cancelled" in out.lower()
    remaining = await repo.active_for_creator(gid, 42)
    assert len(remaining) == 1 and remaining[0].topic == "stocks"


def test_tool_specs_has_edit_tools():
    names = {s["function"]["name"] for s in tool_specs(has_search=False)}
    assert {"edit_reminder", "edit_subscription"} <= names


@pytest.mark.asyncio
async def test_execute_edit_reminder_changes_time(db_session):
    gid, repo = await _mk_reminders(
        db_session
    )  # "play games tonight" + "team meeting in the morning"
    ctx = ToolContext(reminder_repo=repo, guild_pk=gid, commander_id=42)
    out = await execute("edit_reminder", {"query": "meeting", "when": "2099-06-01 09:00"}, ctx)
    await db_session.commit()
    assert "updated" in out.lower()
    hop = next(r for r in await repo.pending_for_guild(gid) if "meeting" in r.message)
    assert hop.remind_at.year == 2099  # time changed to the far future


@pytest.mark.asyncio
async def test_execute_edit_reminder_ambiguous_lists(db_session):
    gid, repo = await _mk_reminders(db_session)
    ctx = ToolContext(reminder_repo=repo, guild_pk=gid, commander_id=42)
    out = await execute("edit_reminder", {"query": "", "when": "2099-06-01 09:00"}, ctx)
    assert "be more specific" in out.lower()  # 2 match -> ask back, don't edit blindly


@pytest.mark.asyncio
async def test_execute_edit_subscription_time_and_topic(db_session):
    from app.repositories.subscription import SubscriptionRepository

    gid = await _guild_for_subs(db_session)
    repo = SubscriptionRepository(db_session)
    await repo.create(guild_id=gid, channel_id=1, creator_id=42, topic="stocks", hour=8, minute=0)
    await db_session.commit()
    ctx = ToolContext(subscription_repo=repo, guild_pk=gid, commander_id=42)

    await execute("edit_subscription", {"query": "stocks", "time": "7:00"}, ctx)
    await db_session.commit()
    assert (await repo.active_for_creator(gid, 42))[0].hour == 7

    await execute("edit_subscription", {"query": "stocks", "topic": "SJC gold price"}, ctx)
    await db_session.commit()
    assert (await repo.active_for_creator(gid, 42))[0].topic == "SJC gold price"


def test_tool_specs_always_has_forget():
    assert "forget" in {s["function"]["name"] for s in tool_specs(has_search=False)}


@pytest.mark.asyncio
async def test_execute_forget_removes_note(db_session):
    import uuid as _uuid

    from app.models.guild import Guild
    from app.repositories.memory_doc import MemoryDocRepository

    gid = _uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    await db_session.commit()
    repo = MemoryDocRepository(db_session)
    await repo.append_note(gid, 'call Khoi "jerk Khoi"')
    await db_session.commit()
    ctx = ToolContext(memory_repo_doc=repo, guild_pk=gid)
    out = await execute("forget", {"query": "jerk Khoi"}, ctx)
    await db_session.commit()
    assert "forgot" in out.lower()
    assert "jerk Khoi" not in await repo.get_doc(gid)


@pytest.mark.asyncio
async def test_execute_forget_no_match():
    out = await execute("forget", {"query": "x"}, ToolContext())
    assert "can't delete" in out.lower()


@pytest.mark.asyncio
async def test_execute_forget_all_clears_with_perm(db_session):
    import uuid as _uuid

    from app.models.guild import Guild
    from app.repositories.memory_doc import MemoryDocRepository

    gid = _uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    await db_session.commit()
    repo = MemoryDocRepository(db_session)
    await repo.append_note(gid, "call An the boss")
    await repo.append_note(gid, "Binh likes coffee")
    await db_session.commit()
    ctx = ToolContext(memory_repo_doc=repo, guild_pk=gid, commander_perms={"manage_guild": True})
    out = await execute("forget", {"all": True}, ctx)
    await db_session.commit()
    assert "wiped" in out.lower()
    assert await repo.get_doc(gid) == ""  # ACTUALLY wiped


@pytest.mark.asyncio
async def test_execute_forget_all_needs_manage_guild():
    # No Manage Server permission -> CAN'T wipe everything (gated like /claw-lore-clear).
    ctx = ToolContext(memory_repo_doc=object(), guild_pk="x", commander_perms={})
    out = await execute("forget", {"all": True}, ctx)
    assert "manage server" in out.lower()
