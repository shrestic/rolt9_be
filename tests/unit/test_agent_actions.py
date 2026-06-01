import functools
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.guild import Guild
from app.repositories.welcome_config import WelcomeConfigRepository
from app.services.ai.actions.registry import (
    ACTION_PERMS,
    DESTRUCTIVE,
    PLUGIN_TOGGLES,
    PendingAction,
    execute,
    stage,
)
from app.services.ai.tools.registry import ToolContext

ALL_PERMS = {
    "manage_roles": True,
    "manage_guild": True,
    "ban_members": True,
    "kick_members": True,
    "moderate_members": True,
}


def _ctx(**kw):
    base = {
        "commander_perms": dict(ALL_PERMS),
        "role_names": ["VIP", "Mod"],
        "target_user_ids": [111],
        "commander_id": 999,
    }
    base.update(kw)
    return ToolContext(**base)


# ---------- stage ----------


@pytest.mark.asyncio
async def test_stage_requires_permission():
    out = await stage("create_role", {"name": "X"}, _ctx(commander_perms={}))
    assert isinstance(out, str) and "quyền" in out.lower()


@pytest.mark.asyncio
async def test_stage_create_role_ok():
    p = await stage("create_role", {"name": "VIP2", "color": "#ff0000"}, _ctx())
    assert isinstance(p, PendingAction)
    assert p.kind == "create_role" and p.destructive is False
    assert p.params["name"] == "VIP2" and p.params["color"] == 0xFF0000


@pytest.mark.asyncio
async def test_stage_assign_role_unknown():
    assert isinstance(await stage("assign_role", {"role_name": "Khong Co"}, _ctx()), str)


@pytest.mark.asyncio
async def test_stage_assign_targets_mentions_else_commander():
    p = await stage("assign_role", {"role_name": "vip"}, _ctx(target_user_ids=[1, 2]))
    assert p.params["role_name"] == "VIP" and p.params["target_ids"] == [1, 2]
    p2 = await stage("assign_role", {"role_name": "VIP"}, _ctx(target_user_ids=[], commander_id=9))
    assert p2.params["target_ids"] == [9]


@pytest.mark.asyncio
async def test_stage_kick_needs_target_and_is_destructive():
    assert isinstance(await stage("kick", {}, _ctx(target_user_ids=[])), str)
    p = await stage("kick", {"reason": "spam"}, _ctx(target_user_ids=[111]))
    assert isinstance(p, PendingAction) and p.destructive is True


@pytest.mark.asyncio
async def test_stage_timeout_minutes():
    assert isinstance(await stage("timeout", {"minutes": 0}, _ctx()), str)
    p = await stage("timeout", {"minutes": 10}, _ctx())
    assert p.params["minutes"] == 10 and p.destructive is True


@pytest.mark.asyncio
async def test_stage_toggle_plugin():
    assert isinstance(
        await stage("toggle_plugin", {"plugin": "nope", "enabled": True}, _ctx()), str
    )
    p = await stage("toggle_plugin", {"plugin": "welcome", "enabled": True}, _ctx())
    assert p.params == {"plugin": "welcome", "enabled": True} and p.destructive is False


@pytest.mark.asyncio
@pytest.mark.parametrize("plugin", list(PLUGIN_TOGGLES))
@pytest.mark.parametrize("enabled", [True, False])
async def test_stage_toggle_every_plugin(plugin, enabled):
    # Mọi plugin trong PLUGIN_TOGGLES đều stage được, cả bật lẫn tắt.
    p = await stage("toggle_plugin", {"plugin": plugin, "enabled": enabled}, _ctx())
    assert isinstance(p, PendingAction)
    assert p.params == {"plugin": plugin, "enabled": enabled}


def test_toggle_plugin_spec_enum_matches_registry():
    # Enum trong spec phải khớp đúng danh sách plugin -> model chỉ chọn plugin hợp lệ.
    from app.services.ai.actions.registry import ACTION_SPECS

    spec = next(s for s in ACTION_SPECS if s["function"]["name"] == "toggle_plugin")
    assert spec["function"]["parameters"]["properties"]["plugin"]["enum"] == list(PLUGIN_TOGGLES)


def test_action_perms_and_destructive():
    assert ACTION_PERMS["ban"] == "ban_members"
    assert ACTION_PERMS["toggle_plugin"] == "manage_guild"
    assert "kick" in DESTRUCTIVE and "create_role" not in DESTRUCTIVE


# ---------- execute ----------


@pytest.mark.asyncio
async def test_execute_toggle_plugin_db(db_session):
    gid = uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=555, name="g", icon_url=None, is_active=True))
    await db_session.commit()
    guild = SimpleNamespace(id=555)
    p = PendingAction("toggle_plugin", False, "", {"plugin": "welcome", "enabled": True})
    out = await execute(p, guild=guild, session=db_session)
    await db_session.commit()
    assert "bật" in out.lower()
    cfg = await WelcomeConfigRepository(db_session).get_or_create(gid)
    assert cfg.enabled is True


@pytest.mark.asyncio
async def test_execute_toggle_plugin_agent_field(db_session):
    # plugin 'agent' flip field agent_enabled (KHÁC field 'enabled') -> verify map đúng field
    from app.repositories.ai_config import AIConfigRepository

    gid = uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=556, name="g", icon_url=None, is_active=True))
    await db_session.commit()
    guild = SimpleNamespace(id=556)
    p = PendingAction("toggle_plugin", False, "", {"plugin": "agent", "enabled": True})
    out = await execute(p, guild=guild, session=db_session)
    await db_session.commit()
    assert "bật" in out.lower()
    cfg = await AIConfigRepository(db_session).get(gid)
    assert cfg.agent_enabled is True


@pytest.mark.asyncio
async def test_execute_create_role_calls_api():
    guild = SimpleNamespace(create_role=AsyncMock())
    p = PendingAction("create_role", False, "", {"name": "VIP", "color": None})
    out = await execute(p, guild=guild, session=None)
    guild.create_role.assert_awaited_once()
    assert "tạo role" in out.lower()


@pytest.mark.asyncio
async def test_execute_create_poll_sends_native_poll():
    channel = SimpleNamespace(send=AsyncMock())
    p = PendingAction(
        "create_poll",
        False,
        "",
        {
            "question": "Tối nay ăn gì?",
            "options": ["Phở", "Cơm tấm"],
            "duration_hours": 24,
            "multiple": False,
        },
    )
    out = await execute(p, guild=None, session=None, channel=channel)
    channel.send.assert_awaited_once()
    # poll Discord native được truyền qua kwarg `poll`
    assert channel.send.call_args.kwargs.get("poll") is not None
    assert "poll" in out.lower()


@pytest.mark.asyncio
async def test_execute_create_poll_needs_channel():
    p = PendingAction("create_poll", False, "", {"question": "x", "options": ["a", "b"]})
    out = await execute(p, guild=None, session=None, channel=None)
    assert "thiếu kênh" in out.lower()


@functools.total_ordering
class _Role:
    def __init__(self, pos):
        self.position = pos
        self.name = f"r{pos}"

    def __le__(self, o):
        return self.position <= o.position

    def __eq__(self, o):
        return self.position == o.position

    def __hash__(self):
        return id(self)


@pytest.mark.asyncio
async def test_execute_kick_calls_api_when_below_bot():
    member = SimpleNamespace(top_role=_Role(1), display_name="Đạt", kick=AsyncMock())
    guild = SimpleNamespace(me=SimpleNamespace(top_role=_Role(10)), get_member=lambda uid: member)
    p = PendingAction("kick", True, "", {"target_ids": [111], "reason": "spam"})
    out = await execute(p, guild=guild, session=None)
    member.kick.assert_awaited_once()
    assert "kick" in out.lower()


@pytest.mark.asyncio
async def test_execute_kick_blocked_by_hierarchy():
    member = SimpleNamespace(top_role=_Role(10), display_name="Sếp", kick=AsyncMock())
    guild = SimpleNamespace(me=SimpleNamespace(top_role=_Role(5)), get_member=lambda uid: member)
    p = PendingAction("kick", True, "", {"target_ids": [111], "reason": ""})
    out = await execute(p, guild=guild, session=None)
    member.kick.assert_not_awaited()
    assert "cao hơn" in out.lower()


class _AsyncIter:
    """Async-iterator giả cho guild.bans()."""

    def __init__(self, items):
        self._items = items

    def __aiter__(self):
        self._it = iter(self._items)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration from None


# ---------- unban / untimeout: stage ----------


@pytest.mark.asyncio
async def test_stage_unban_needs_user_or_mention():
    # Không @ được + không nhập tên/ID -> lỗi
    assert isinstance(await stage("unban", {}, _ctx(target_user_ids=[])), str)
    p = await stage("unban", {"user": "BadGuy"}, _ctx(target_user_ids=[]))
    assert isinstance(p, PendingAction) and p.destructive is False
    assert p.params["query"] == "BadGuy"


@pytest.mark.asyncio
async def test_stage_untimeout_needs_target():
    assert isinstance(await stage("untimeout", {}, _ctx(target_user_ids=[])), str)
    p = await stage("untimeout", {}, _ctx(target_user_ids=[111]))
    assert isinstance(p, PendingAction) and p.destructive is False


def test_unban_untimeout_perms_non_destructive():
    assert ACTION_PERMS["unban"] == "ban_members"
    assert ACTION_PERMS["untimeout"] == "moderate_members"
    assert "unban" not in DESTRUCTIVE and "untimeout" not in DESTRUCTIVE


def test_action_specs_include_unban_untimeout():
    from app.services.ai.actions.registry import ACTION_SPECS

    names = {s["function"]["name"] for s in ACTION_SPECS}
    assert {"unban", "untimeout"} <= names


# ---------- unban / untimeout + batch: execute ----------


@pytest.mark.asyncio
async def test_execute_untimeout_clears_timeout():
    member = SimpleNamespace(timeout=AsyncMock(), display_name="An", top_role=_Role(1))
    guild = SimpleNamespace(me=SimpleNamespace(top_role=_Role(10)), get_member=lambda uid: member)
    p = PendingAction("untimeout", False, "", {"target_ids": [111], "reason": ""})
    out = await execute(p, guild=guild, session=None)
    member.timeout.assert_awaited_once_with(None, reason=None)  # None = gỡ timeout
    assert "gỡ timeout 1" in out.lower()


@pytest.mark.asyncio
async def test_execute_unban_by_name():
    banned = SimpleNamespace(user=SimpleNamespace(id=222, name="BadGuy"))
    guild = SimpleNamespace(bans=lambda: _AsyncIter([banned]), unban=AsyncMock())
    p = PendingAction("unban", False, "", {"target_ids": [], "query": "badguy", "reason": ""})
    out = await execute(p, guild=guild, session=None)
    guild.unban.assert_awaited_once()
    assert "gỡ ban 1" in out.lower()


@pytest.mark.asyncio
async def test_execute_unban_by_id():
    banned = SimpleNamespace(user=SimpleNamespace(id=222, name="BadGuy"))
    guild = SimpleNamespace(bans=lambda: _AsyncIter([banned]), unban=AsyncMock())
    p = PendingAction("unban", False, "", {"target_ids": [222], "query": "", "reason": ""})
    out = await execute(p, guild=guild, session=None)
    guild.unban.assert_awaited_once()
    assert "gỡ ban 1" in out.lower()


@pytest.mark.asyncio
async def test_execute_unban_no_match():
    banned = SimpleNamespace(user=SimpleNamespace(id=222, name="BadGuy"))
    guild = SimpleNamespace(bans=lambda: _AsyncIter([banned]), unban=AsyncMock())
    p = PendingAction("unban", False, "", {"target_ids": [999], "query": "nope", "reason": ""})
    out = await execute(p, guild=guild, session=None)
    guild.unban.assert_not_awaited()
    assert "không tìm thấy" in out.lower()


@pytest.mark.asyncio
async def test_execute_ban_user_who_left_uses_object():
    # get_member None (đã rời) -> vẫn ban được theo ID
    guild = SimpleNamespace(
        me=SimpleNamespace(top_role=_Role(10)), get_member=lambda uid: None, ban=AsyncMock()
    )
    p = PendingAction("ban", True, "", {"target_ids": [111], "reason": "spam"})
    out = await execute(p, guild=guild, session=None)
    guild.ban.assert_awaited_once()
    assert "ban 1" in out.lower()


@pytest.mark.asyncio
async def test_execute_kick_batch_continues_past_blocked():
    # 1 người role cao hơn bot (bỏ qua), 1 người thấp hơn (kick) -> KHÔNG abort cả lô
    boss = SimpleNamespace(top_role=_Role(10), display_name="Sếp", kick=AsyncMock())
    noob = SimpleNamespace(top_role=_Role(1), display_name="Noob", kick=AsyncMock())
    members = {1: boss, 2: noob}
    guild = SimpleNamespace(
        me=SimpleNamespace(top_role=_Role(5)), get_member=lambda uid: members[uid]
    )
    p = PendingAction("kick", True, "", {"target_ids": [1, 2], "reason": ""})
    out = await execute(p, guild=guild, session=None)
    boss.kick.assert_not_awaited()
    noob.kick.assert_awaited_once()
    assert "1 người" in out and "Sếp" in out
