import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.bot.cogs.karma as karma_mod
from app.bot.cogs.karma import KarmaCog
from app.services.karma.karma_service import GiveResult, KarmaStanding


def test_cog_registers_group():
    cog = KarmaCog(MagicMock(), MagicMock())
    names = {c.name for c in cog.get_app_commands()}
    assert "karma" in names


def _patch(monkeypatch, stub):
    @contextlib.asynccontextmanager
    async def fake_scope():
        yield MagicMock()

    monkeypatch.setattr(karma_mod, "session_scope", fake_scope)
    monkeypatch.setattr(karma_mod, "_build_service", lambda session: stub)


def _interaction(user_id=1):
    inter = MagicMock()
    inter.guild_id = 100
    inter.user = SimpleNamespace(id=user_id, mention=f"<@{user_id}>")
    inter.response = SimpleNamespace(defer=AsyncMock())
    inter.followup = SimpleNamespace(send=AsyncMock())
    return inter


def _member(uid=2, bot=False):
    return SimpleNamespace(id=uid, bot=bot, mention=f"<@{uid}>")


@pytest.mark.asyncio
async def test_give_reports(monkeypatch):
    stub = MagicMock()
    stub.give = AsyncMock(return_value=GiveResult(receiver_points=5, receiver_rank=2))
    _patch(monkeypatch, stub)
    cog = KarmaCog(MagicMock(), MagicMock())
    inter = _interaction(user_id=1)
    await cog.karma_give.callback(cog, inter, _member(2))
    msg = inter.followup.send.call_args.args[0]
    assert "5" in msg


@pytest.mark.asyncio
async def test_give_to_bot_rejected(monkeypatch):
    stub = MagicMock()
    stub.give = AsyncMock()
    _patch(monkeypatch, stub)
    cog = KarmaCog(MagicMock(), MagicMock())
    inter = _interaction(user_id=1)
    await cog.karma_give.callback(cog, inter, _member(9, bot=True))
    msg = inter.followup.send.call_args.args[0]
    assert "❌" in msg
    stub.give.assert_not_awaited()


@pytest.mark.asyncio
async def test_give_self_rejected_in_cog(monkeypatch):
    stub = MagicMock()
    stub.give = AsyncMock()
    _patch(monkeypatch, stub)
    cog = KarmaCog(MagicMock(), MagicMock())
    inter = _interaction(user_id=1)
    await cog.karma_give.callback(cog, inter, _member(1))
    msg = inter.followup.send.call_args.args[0]
    assert "❌" in msg
    stub.give.assert_not_awaited()


@pytest.mark.asyncio
async def test_view_reports_points(monkeypatch):
    stub = MagicMock()
    stub.get_standing = AsyncMock(return_value=KarmaStanding(points=7, rank=3))
    _patch(monkeypatch, stub)
    cog = KarmaCog(MagicMock(), MagicMock())
    inter = _interaction()
    await cog.karma_view.callback(cog, inter, None)
    msg = inter.followup.send.call_args.args[0]
    assert "7" in msg


@pytest.mark.asyncio
async def test_top_renders(monkeypatch):
    stub = MagicMock()
    stub.leaderboard = AsyncMock(return_value=([SimpleNamespace(user_id=2, points=5)], 1))
    _patch(monkeypatch, stub)
    cog = KarmaCog(MagicMock(), MagicMock())
    inter = _interaction()
    await cog.karma_top.callback(cog, inter)
    msg = inter.followup.send.call_args.args[0]
    assert "5" in msg
