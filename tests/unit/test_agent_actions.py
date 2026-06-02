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
async def test_stage_assign_unknown_role_defers_to_execute():
    # assign role CHƯA tồn tại -> KHÔNG từ chối sớm (có thể do create_role tạo cùng lượt);
    # stage với tên thô, để execute kiểm tra lúc chạy.
    p = await stage("assign_role", {"role_name": "Mới Toanh"}, _ctx())
    assert isinstance(p, PendingAction) and p.params["role_name"] == "Mới Toanh"


@pytest.mark.asyncio
async def test_stage_remove_unknown_role_still_rejects():
    # remove/delete vẫn cần role có sẵn -> từ chối sớm cho rõ
    assert isinstance(await stage("remove_role", {"role_name": "Khong Co"}, _ctx()), str)
    assert isinstance(await stage("delete_role", {"role_name": "Khong Co"}, _ctx()), str)


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
async def test_stage_ban_owner_rejected_immediately():
    # Ban/kick/timeout CHỦ SERVER -> từ chối NGAY lúc stage (chuỗi lỗi), KHÔNG ra PendingAction
    # (đỡ hiện nút xác nhận rồi mới báo). owner_id lấy từ guild_snapshot.
    ctx = _ctx(target_user_ids=[705], guild_snapshot={"owner_id": 705})
    for kind in ("ban", "kick", "timeout"):
        out = await stage(kind, {}, ctx)
        assert isinstance(out, str) and "chủ server" in out.lower()
    # người KHÁC owner -> vẫn stage bình thường
    p = await stage("ban", {}, _ctx(target_user_ids=[111], guild_snapshot={"owner_id": 705}))
    assert isinstance(p, PendingAction)


@pytest.mark.asyncio
async def test_stage_timeout_minutes():
    # không nói phút (hoặc phút không hợp lệ) -> MẶC ĐỊNH 10, KHÔNG hỏi lại (tránh bẫy multi-turn)
    p0 = await stage("timeout", {}, _ctx())
    assert isinstance(p0, PendingAction) and p0.params["minutes"] == 10
    p_bad = await stage("timeout", {"minutes": 0}, _ctx())
    assert isinstance(p_bad, PendingAction) and p_bad.params["minutes"] == 10
    p = await stage("timeout", {"minutes": 5}, _ctx())
    assert p.params["minutes"] == 5 and p.destructive is True


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


@pytest.mark.asyncio
async def test_execute_delete_poll_finds_bot_poll():
    # tin có poll DO BOT tạo -> xoá; tin thường bỏ qua
    poll_msg = SimpleNamespace(poll=object(), author=SimpleNamespace(id=1), delete=AsyncMock())
    plain = SimpleNamespace(poll=None, author=SimpleNamespace(id=1))
    channel = SimpleNamespace(history=lambda limit: _AsyncIter([plain, poll_msg]))
    guild = SimpleNamespace(me=SimpleNamespace(id=1))
    p = PendingAction("delete_poll", False, "", {})
    out = await execute(p, guild=guild, session=None, channel=channel)
    poll_msg.delete.assert_awaited_once()
    assert "xoá poll" in out.lower()


@pytest.mark.asyncio
async def test_execute_delete_poll_none_found():
    plain = SimpleNamespace(poll=None, author=SimpleNamespace(id=1))
    channel = SimpleNamespace(history=lambda limit: _AsyncIter([plain]))
    guild = SimpleNamespace(me=SimpleNamespace(id=1))
    p = PendingAction("delete_poll", False, "", {})
    out = await execute(p, guild=guild, session=None, channel=channel)
    assert "không thấy poll" in out.lower()


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


def test_resolve_member_ids_matches_other_bot_by_name():
    # Ban/kick BOT khác (vd 'Jockie Music' music bot) qua tên -> phải match được (trước đây loại bot).
    from app.services.ai.actions.registry import _resolve_member_ids

    jockie = SimpleNamespace(id=222, name="Jockie Music", display_name="Jockie Music", bot=True)
    guild = SimpleNamespace(members=[jockie], me=SimpleNamespace(id=1))
    ids, err = _resolve_member_ids(guild, [], "Jockie Music")
    assert ids == [222] and err is None


def test_resolve_member_ids_excludes_self_bot():
    # KHÔNG tự match CHÍNH rolt9 (đừng tự ban mình) dù tên khớp.
    from app.services.ai.actions.registry import _resolve_member_ids

    me = SimpleNamespace(id=1, name="rolt9", display_name="rolt9", bot=True)
    guild = SimpleNamespace(members=[me], me=SimpleNamespace(id=1))
    ids, err = _resolve_member_ids(guild, [], "rolt9")
    assert ids == [] and err  # không thấy ai (đã loại chính bot)


@pytest.mark.asyncio
async def test_execute_ban_blocks_server_owner():
    # CHỦ SERVER không ban được (Discord cấm bất kể role) -> chặn rõ, KHÔNG gọi guild.ban.
    member = SimpleNamespace(id=999, top_role=_Role(1), display_name="shrestic")
    guild = SimpleNamespace(
        me=SimpleNamespace(top_role=_Role(10)),
        get_member=lambda uid: member,
        owner_id=999,  # shrestic = chủ server
        ban=AsyncMock(),
    )
    p = PendingAction("ban", True, "", {"target_ids": [999], "reason": ""})
    out = await execute(p, guild=guild, session=None)
    guild.ban.assert_not_awaited()  # không hề gọi ban owner
    assert "chủ server" in out.lower()  # báo rõ lý do


@pytest.mark.asyncio
async def test_execute_ban_reports_discord_rejection_instead_of_crashing():
    # Discord từ chối lúc thực thi (Forbidden…) -> báo lại, KHÔNG văng exception.
    import discord

    async def boom(*a, **k):
        raise discord.DiscordException("forbidden")

    member = SimpleNamespace(id=5, top_role=_Role(1), display_name="X")
    guild = SimpleNamespace(
        me=SimpleNamespace(top_role=_Role(10)),
        get_member=lambda uid: member,
        owner_id=None,
        ban=AsyncMock(side_effect=boom),
    )
    p = PendingAction("ban", True, "", {"target_ids": [5], "reason": ""})
    out = await execute(p, guild=guild, session=None)  # không raise
    assert "từ chối" in out.lower()


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
    guild = SimpleNamespace(bans=lambda limit=None: _AsyncIter([banned]), unban=AsyncMock())
    p = PendingAction("unban", False, "", {"target_ids": [], "query": "badguy", "reason": ""})
    out = await execute(p, guild=guild, session=None)
    guild.unban.assert_awaited_once()
    assert "gỡ ban" in out.lower() and "BadGuy" in out


@pytest.mark.asyncio
async def test_execute_unban_by_id():
    banned = SimpleNamespace(user=SimpleNamespace(id=222, name="BadGuy"))
    guild = SimpleNamespace(bans=lambda limit=None: _AsyncIter([banned]), unban=AsyncMock())
    p = PendingAction("unban", False, "", {"target_ids": [222], "query": "", "reason": ""})
    out = await execute(p, guild=guild, session=None)
    guild.unban.assert_awaited_once()
    assert "gỡ ban" in out.lower()


@pytest.mark.asyncio
async def test_execute_unban_normalized_name_match():
    # tên có dấu gạch/space vẫn khớp query (vd "deleted-user" ~ "deleted user")
    banned = SimpleNamespace(user=SimpleNamespace(id=7, name="Deleted User"))
    guild = SimpleNamespace(bans=lambda limit=None: _AsyncIter([banned]), unban=AsyncMock())
    p = PendingAction("unban", False, "", {"target_ids": [], "query": "deleted-user", "reason": ""})
    out = await execute(p, guild=guild, session=None)
    guild.unban.assert_awaited_once()
    assert "gỡ ban" in out.lower()


@pytest.mark.asyncio
async def test_execute_unban_no_match_lists_bans_with_ids():
    # không khớp -> liệt kê ban list kèm ID để gỡ theo ID (tài khoản xoá tên khó gõ)
    banned = SimpleNamespace(user=SimpleNamespace(id=222, name="BadGuy"))
    guild = SimpleNamespace(bans=lambda limit=None: _AsyncIter([banned]), unban=AsyncMock())
    p = PendingAction("unban", False, "", {"target_ids": [999], "query": "nope", "reason": ""})
    out = await execute(p, guild=guild, session=None)
    guild.unban.assert_not_awaited()
    assert "không thấy" in out.lower()
    assert "BadGuy" in out and "222" in out  # liệt kê tên + ID


@pytest.mark.asyncio
async def test_execute_unban_empty_ban_list():
    guild = SimpleNamespace(bans=lambda limit=None: _AsyncIter([]), unban=AsyncMock())
    p = PendingAction("unban", False, "", {"target_ids": [], "query": "ai đó", "reason": ""})
    out = await execute(p, guild=guild, session=None)
    guild.unban.assert_not_awaited()
    assert "trống" in out.lower()


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


def test_create_role_sorts_before_assign():
    # cog xếp create_role chạy trước -> 'tạo role X rồi gán X' trong 1 câu chạy được
    pend = [
        PendingAction("assign_role", False, "", {"role_name": "X", "target_ids": [1]}),
        PendingAction("create_role", False, "", {"name": "X", "color": None}),
    ]
    ordered = sorted(pend, key=lambda a: 0 if a.kind == "create_role" else 1)
    assert [p.kind for p in ordered] == ["create_role", "assign_role"]


# ---------- kick/ban/timeout: tìm theo TÊN khi không @ mention được ----------


@pytest.mark.asyncio
async def test_stage_kick_accepts_name_query():
    # gõ "@samnguyen" dạng text (không mention thật) -> stage được nhờ 'user'
    p = await stage("kick", {"user": "samnguyen"}, _ctx(target_user_ids=[]))
    assert isinstance(p, PendingAction) and p.params["query"] == "samnguyen"


@pytest.mark.asyncio
async def test_execute_kick_resolves_name_when_no_mention():
    noob = SimpleNamespace(
        id=5, bot=False, name="samnguyen", display_name="Sam", top_role=_Role(1), kick=AsyncMock()
    )
    guild = SimpleNamespace(
        me=SimpleNamespace(top_role=_Role(10)),
        members=[noob],
        get_member=lambda uid: noob if uid == 5 else None,
    )
    p = PendingAction("kick", True, "", {"target_ids": [], "query": "samnguyen", "reason": ""})
    out = await execute(p, guild=guild, session=None)
    noob.kick.assert_awaited_once()
    assert "kick 1" in out.lower()


@pytest.mark.asyncio
async def test_execute_kick_ambiguous_name_asks():
    a = SimpleNamespace(
        id=1, bot=False, name="sam1", display_name="Sam A", top_role=_Role(1), kick=AsyncMock()
    )
    b = SimpleNamespace(
        id=2, bot=False, name="sam2", display_name="Sam B", top_role=_Role(1), kick=AsyncMock()
    )
    guild = SimpleNamespace(
        me=SimpleNamespace(top_role=_Role(10)), members=[a, b], get_member=lambda uid: None
    )
    p = PendingAction("kick", True, "", {"target_ids": [], "query": "sam", "reason": ""})
    out = await execute(p, guild=guild, session=None)
    a.kick.assert_not_awaited()
    assert "rõ giùm" in out.lower() and "2 người" in out


@pytest.mark.asyncio
async def test_execute_kick_name_not_found():
    guild = SimpleNamespace(
        me=SimpleNamespace(top_role=_Role(10)), members=[], get_member=lambda uid: None
    )
    p = PendingAction("kick", True, "", {"target_ids": [], "query": "nobody", "reason": ""})
    out = await execute(p, guild=guild, session=None)
    assert "không tìm thấy" in out.lower()


@pytest.mark.asyncio
async def test_stage_untimeout_accepts_name():
    p = await stage("untimeout", {"user": "samnguyen"}, _ctx(target_user_ids=[]))
    assert isinstance(p, PendingAction) and p.params["query"] == "samnguyen"


@pytest.mark.asyncio
async def test_execute_untimeout_resolves_name():
    m = SimpleNamespace(id=5, bot=False, name="samnguyen", display_name="Sam", timeout=AsyncMock())
    guild = SimpleNamespace(members=[m], get_member=lambda uid: m if uid == 5 else None)
    p = PendingAction(
        "untimeout", False, "", {"target_ids": [], "query": "samnguyen", "reason": ""}
    )
    out = await execute(p, guild=guild, session=None)
    m.timeout.assert_awaited_once_with(None, reason=None)
    assert "gỡ timeout 1" in out.lower()
