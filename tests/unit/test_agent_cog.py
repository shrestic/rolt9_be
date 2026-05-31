import contextlib
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.bot.cogs.agent as agent_mod
from app.bot.cogs.agent import AGENT_COOLDOWN, AgentCog, CooldownTracker, is_addressed


class _User:
    def __init__(self, id, bot=False):
        self.id = id
        self.bot = bot
        self.display_name = f"u{id}"


class _Ref:
    def __init__(self, mid):
        self.message_id = mid


class _Msg:
    def __init__(self, *, author=None, mentions=None, reference=None, guild=True):
        self.author = author or _User(2)
        self.mentions = mentions or []
        self.reference = reference
        self.guild = SimpleNamespace(id=100) if guild else None
        self.channel = SimpleNamespace(id=10)
        self.clean_content = "hello"
        self.reply = AsyncMock(return_value=SimpleNamespace(id=555))


# ---------- pure helpers ----------


def test_is_addressed_by_mention():
    bot = _User(1)
    assert is_addressed(_Msg(mentions=[_User(1)]), bot) is True
    assert is_addressed(_Msg(mentions=[_User(2)]), bot) is False


def test_is_addressed_by_reply_present():
    bot = _User(1)
    assert is_addressed(_Msg(reference=_Ref(99)), bot) is True
    assert is_addressed(_Msg(), bot) is False


def test_cooldown_tracker():
    t = CooldownTracker(AGENT_COOLDOWN)
    assert t.ready(42, now=100.0) is True
    t.mark(42, now=100.0)
    assert t.ready(42, now=100.0 + AGENT_COOLDOWN - 1) is False
    assert t.ready(42, now=100.0 + AGENT_COOLDOWN + 1) is True


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
    stub.respond = AsyncMock(return_value=(cid, "trả lời"))
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
    stub.respond = AsyncMock(return_value=(cid, "ok"))
    stub.remember = AsyncMock()
    _patch(monkeypatch, stub)
    cog = _cog()
    u = _User(2)
    await cog.on_message(_Msg(author=u, mentions=[_User(1)]))
    await cog.on_message(_Msg(author=u, mentions=[_User(1)]))  # ngay lập tức -> cooldown
    assert stub.respond.await_count == 1
