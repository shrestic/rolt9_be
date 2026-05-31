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
async def test_execute_create_role_calls_api():
    guild = SimpleNamespace(create_role=AsyncMock())
    p = PendingAction("create_role", False, "", {"name": "VIP", "color": None})
    out = await execute(p, guild=guild, session=None)
    guild.create_role.assert_awaited_once()
    assert "tạo role" in out.lower()


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
