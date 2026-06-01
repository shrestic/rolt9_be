import contextlib
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.bot.cogs.agent as agent_mod
from app.bot.cogs.agent import AGENT_COOLDOWN, AgentCog, CooldownTracker, is_addressed


class _User:
    def __init__(self, id, bot=False, name="rolt9", perms=None):
        self.id = id
        self.bot = bot
        self.name = name
        self.display_name = f"u{id}"
        flags = {
            "manage_guild": False,
            "manage_roles": False,
            "ban_members": False,
            "kick_members": False,
            "moderate_members": False,
        }
        flags.update(perms or {})
        self.guild_permissions = SimpleNamespace(**flags)


class _Ref:
    def __init__(self, mid):
        self.message_id = mid


class _Typing:
    """Async context manager rỗng giả cho channel.typing()."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Msg:
    def __init__(
        self,
        *,
        author=None,
        mentions=None,
        reference=None,
        guild=True,
        content="hello",
        clean_content="hello",
        role_mentions=None,
        me_role_ids=(),
    ):
        self.author = author or _User(2)
        self.mentions = mentions or []
        self.reference = reference
        self.content = content
        self.role_mentions = role_mentions or []
        self.guild = (
            SimpleNamespace(
                id=100,
                member_count=5,
                roles=[SimpleNamespace(name="@everyone"), SimpleNamespace(name="Mod")],
                channels=[SimpleNamespace(name="general")],
                me=SimpleNamespace(roles=[SimpleNamespace(id=rid) for rid in me_role_ids]),
            )
            if guild
            else None
        )
        self.channel = SimpleNamespace(id=10, send=AsyncMock(), typing=lambda: _Typing())
        self.clean_content = clean_content
        self.reply = AsyncMock(return_value=SimpleNamespace(id=555))


# ---------- pure helpers ----------


def test_is_addressed_by_mention():
    bot = _User(1)
    assert is_addressed(_Msg(mentions=[_User(1)]), bot) is True
    assert is_addressed(_Msg(mentions=[_User(2)]), bot) is False


def test_is_addressed_by_reply_present():
    bot = _User(1)
    assert is_addressed(_Msg(reference=_Ref(99)), bot) is True
    assert is_addressed(_Msg(content="chào mọi người"), bot) is False


def test_is_addressed_by_name_text():
    bot = _User(1, name="rolt9")
    # gõ "@rolt9 ..." dạng text (mention không thành) vẫn được nhận
    assert is_addressed(_Msg(content="@rolt9 mấy giờ rồi?"), bot) is True
    assert is_addressed(_Msg(content="rolt9 ơi giúp tí"), bot) is True
    assert is_addressed(_Msg(content="nói chuyện bình thường"), bot) is False


def test_is_addressed_by_clean_content_role_render():
    bot = _User(1, name="rolt9")
    # Mention ROLE -> content có "<@&..>" nhưng clean_content render thành "@rolt9"
    msg = _Msg(content="<@&999> mấy giờ", clean_content="@rolt9 mấy giờ")
    assert is_addressed(msg, bot) is True


def test_is_addressed_by_bot_role_mention():
    bot = _User(1, name="rolt9")
    role = SimpleNamespace(id=999)
    msg = _Msg(
        content="<@&999> hi", clean_content="@SomeRole hi", role_mentions=[role], me_role_ids=(999,)
    )
    assert is_addressed(msg, bot) is True


def test_cooldown_tracker():
    t = CooldownTracker(AGENT_COOLDOWN)
    assert t.ready(7, 42, now=100.0) is True
    t.mark(7, 42, now=100.0)
    assert t.ready(7, 42, now=100.0 + AGENT_COOLDOWN - 1) is False
    assert t.ready(7, 42, now=100.0 + AGENT_COOLDOWN + 1) is True


def test_cooldown_tracker_scoped_by_guild():
    # Cùng 1 user nhưng khác guild -> cooldown độc lập, không chặn nhầm chéo server.
    t = CooldownTracker(AGENT_COOLDOWN)
    t.mark(7, 42, now=100.0)  # user 42 ở guild 7
    assert t.ready(7, 42, now=100.0) is False  # cùng (guild, user) -> đang cooldown
    assert t.ready(8, 42, now=100.0) is True  # cùng user, guild khác -> KHÔNG bị chặn


# ---------- on_message glue (patched session_scope + stub service) ----------


def _patch(monkeypatch, stub):
    @contextlib.asynccontextmanager
    async def fake_scope():
        yield MagicMock()

    monkeypatch.setattr(agent_mod, "session_scope", fake_scope)
    monkeypatch.setattr(agent_mod, "_build_service", lambda session: stub)


def _cog():
    bot = MagicMock()
    bot.user = _User(1)
    return AgentCog(bot, MagicMock())


@pytest.mark.asyncio
async def test_on_message_replies_and_remembers(monkeypatch):
    cid = uuid.uuid4()
    stub = MagicMock()
    stub.respond = AsyncMock(return_value=(cid, "trả lời", []))
    stub.remember = AsyncMock()
    _patch(monkeypatch, stub)
    cog = _cog()
    msg = _Msg(author=_User(2), mentions=[_User(1)])
    await cog.on_message(msg)
    msg.reply.assert_awaited_once()
    stub.respond.assert_awaited_once()
    stub.remember.assert_awaited_once()
    # bot_message_id lấy từ tin đã gửi (555)
    assert stub.remember.call_args.kwargs["bot_message_id"] == 555
    # cog gom snapshot server (member_count + roles trừ @everyone) truyền vào respond
    snap = stub.respond.call_args.kwargs["server_snapshot"]
    assert snap["member_count"] == 5
    assert snap["roles"] == ["Mod"]


@pytest.mark.asyncio
async def test_on_message_ignores_not_addressed(monkeypatch):
    stub = MagicMock()
    stub.respond = AsyncMock()
    _patch(monkeypatch, stub)
    cog = _cog()
    await cog.on_message(_Msg(author=_User(2)))  # không mention, không reply
    stub.respond.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_message_ignores_bot_author(monkeypatch):
    stub = MagicMock()
    stub.respond = AsyncMock()
    _patch(monkeypatch, stub)
    cog = _cog()
    await cog.on_message(_Msg(author=_User(2, bot=True), mentions=[_User(1)]))
    stub.respond.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_message_none_result_no_reply(monkeypatch):
    stub = MagicMock()
    stub.respond = AsyncMock(return_value=None)  # agent off / sai kênh
    stub.remember = AsyncMock()
    _patch(monkeypatch, stub)
    cog = _cog()
    msg = _Msg(author=_User(2), mentions=[_User(1)])
    await cog.on_message(msg)
    msg.reply.assert_not_awaited()
    stub.remember.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_message_value_error_replies_error(monkeypatch):
    stub = MagicMock()
    stub.respond = AsyncMock(side_effect=ValueError("hết budget"))
    _patch(monkeypatch, stub)
    cog = _cog()
    msg = _Msg(author=_User(2), mentions=[_User(1)])
    await cog.on_message(msg)
    msg.reply.assert_awaited_once()
    assert "❌" in msg.reply.call_args.args[0]


@pytest.mark.asyncio
async def test_on_message_cooldown_blocks_second(monkeypatch):
    cid = uuid.uuid4()
    stub = MagicMock()
    stub.respond = AsyncMock(return_value=(cid, "ok", []))
    stub.remember = AsyncMock()
    _patch(monkeypatch, stub)
    cog = _cog()
    u = _User(2)
    await cog.on_message(_Msg(author=u, mentions=[_User(1)]))
    await cog.on_message(_Msg(author=u, mentions=[_User(1)]))  # ngay lập tức -> cooldown
    assert stub.respond.await_count == 1


# ---------- actions (perms + pending handling) ----------

from app.bot.cogs.agent import confirm_perm_ok, perms_dict  # noqa: E402
from app.services.ai.actions.registry import PendingAction  # noqa: E402


def test_perms_dict_and_confirm_perm_ok():
    gp = SimpleNamespace(
        manage_guild=True,
        manage_roles=False,
        ban_members=True,
        kick_members=False,
        moderate_members=False,
    )
    d = perms_dict(gp)
    assert d["manage_guild"] is True and d["ban_members"] is True and d["manage_roles"] is False
    assert confirm_perm_ok("ban", d) is True  # cần ban_members -> có
    assert confirm_perm_ok("create_role", d) is False  # cần manage_roles -> không


@pytest.mark.asyncio
async def test_on_message_executes_safe_action(monkeypatch):
    cid = uuid.uuid4()
    safe = PendingAction(
        "toggle_plugin", False, "Bật welcome", {"plugin": "welcome", "enabled": True}
    )
    stub = MagicMock()
    stub.respond = AsyncMock(return_value=(cid, "ok", [safe]))
    stub.remember = AsyncMock()
    _patch(monkeypatch, stub)
    run_mock = AsyncMock(return_value="Đã bật welcome.")
    monkeypatch.setattr(agent_mod, "run_action", run_mock)
    cog = _cog()
    msg = _Msg(author=_User(2), mentions=[_User(1)])
    await cog.on_message(msg)
    run_mock.assert_awaited_once()  # action an toàn -> chạy ngay
    # Báo theo KẾT QUẢ THẬT, KHÔNG gửi prose "ok" của model (tránh khai khống)
    reply_text = msg.reply.call_args.args[0]
    assert "✅" in reply_text and "welcome" in reply_text.lower()
    # remember lưu kết quả thật, không lưu "ok"
    assert stub.remember.call_args.kwargs["assistant_text"] != "ok"


@pytest.mark.asyncio
async def test_on_message_destructive_sends_confirm(monkeypatch):
    cid = uuid.uuid4()
    danger = PendingAction("ban", True, "Ban 1 người", {"target_ids": [9], "reason": ""})
    stub = MagicMock()
    stub.respond = AsyncMock(return_value=(cid, "ok", [danger]))
    stub.remember = AsyncMock()
    _patch(monkeypatch, stub)
    run_mock = AsyncMock()
    monkeypatch.setattr(agent_mod, "run_action", run_mock)
    cog = _cog()
    msg = _Msg(author=_User(2), mentions=[_User(1)])
    await cog.on_message(msg)
    msg.channel.send.assert_awaited_once()  # gửi nút xác nhận
    run_mock.assert_not_awaited()  # CHƯA execute (chờ ✅)


class _HistMsg:
    """Tin nhắn giả cho channel.history()."""

    def __init__(self, who, text):
        self.clean_content = text
        self.author = SimpleNamespace(display_name=who)


class _HistChannel:
    def __init__(self, msgs, *, raises=False):
        self._msgs = msgs
        self._raises = raises

    def history(self, *, limit, before):
        chan = self

        class _It:
            def __aiter__(self_inner):
                self_inner._i = iter(chan._msgs)
                return self_inner

            async def __anext__(self_inner):
                if chan._raises:
                    raise agent_mod.discord.DiscordException("boom")
                try:
                    return next(self_inner._i)
                except StopIteration:
                    raise StopAsyncIteration

        return _It()


@pytest.mark.asyncio
async def test_collect_channel_context_orders_oldest_first():
    # history() trả mới->cũ; helper phải đảo lại thành cũ->mới + format 'Tên: nội dung'
    ch = _HistChannel([_HistMsg("An", "tin moi"), _HistMsg("Phong", "tin cu")])
    out = await agent_mod.collect_channel_context(ch, before=object())
    assert out == "Phong: tin cu\nAn: tin moi"


@pytest.mark.asyncio
async def test_collect_channel_context_swallows_errors():
    ch = _HistChannel([], raises=True)
    assert await agent_mod.collect_channel_context(ch, before=object()) == ""
