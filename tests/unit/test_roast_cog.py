import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from discord import app_commands

import app.bot.cogs.roast as roast_mod
from app.bot.cogs.roast import RoastCog


def test_cog_registers_command():
    cog = RoastCog(MagicMock(), MagicMock())
    names = {c.name for c in cog.get_app_commands()}
    assert "roast" in names


def _patch(monkeypatch, stub):
    @contextlib.asynccontextmanager
    async def fake_scope():
        yield MagicMock()

    monkeypatch.setattr(roast_mod, "session_scope", fake_scope)
    monkeypatch.setattr(roast_mod, "_build_service", lambda session: stub)


def _interaction(user_id=1):
    inter = MagicMock()
    inter.guild_id = 100
    inter.user = SimpleNamespace(id=user_id, mention=f"<@{user_id}>")
    inter.response = SimpleNamespace(
        defer=AsyncMock(), send_message=AsyncMock(), is_done=MagicMock(return_value=True)
    )
    inter.followup = SimpleNamespace(send=AsyncMock())
    return inter


def _member(uid=2, bot=False):
    return SimpleNamespace(id=uid, bot=bot, mention=f"<@{uid}>", display_name="An")


@pytest.mark.asyncio
async def test_roast_replies(monkeypatch):
    stub = MagicMock()
    stub.roast = AsyncMock(return_value="Dull as a lump of clay.")
    _patch(monkeypatch, stub)
    cog = RoastCog(MagicMock(), MagicMock())
    inter = _interaction()
    await cog.roast.callback(cog, inter, _member(2))
    msg = inter.followup.send.call_args.args[0]
    assert "Dull as a lump of clay." in msg


@pytest.mark.asyncio
async def test_roast_bot_rejected(monkeypatch):
    stub = MagicMock()
    stub.roast = AsyncMock()
    _patch(monkeypatch, stub)
    cog = RoastCog(MagicMock(), MagicMock())
    inter = _interaction()
    await cog.roast.callback(cog, inter, _member(9, bot=True))
    msg = inter.response.send_message.call_args.args[0]
    assert "❌" in msg
    stub.roast.assert_not_awaited()


@pytest.mark.asyncio
async def test_roast_error_friendly(monkeypatch):
    stub = MagicMock()
    stub.roast = AsyncMock(side_effect=ValueError("AI is not enabled yet"))
    _patch(monkeypatch, stub)
    cog = RoastCog(MagicMock(), MagicMock())
    inter = _interaction()
    await cog.roast.callback(cog, inter, _member(2))
    msg = inter.followup.send.call_args.args[0]
    assert "❌" in msg


@pytest.mark.asyncio
async def test_cooldown_error_handled():
    cog = RoastCog(MagicMock(), MagicMock())
    inter = _interaction()
    err = app_commands.CommandOnCooldown.__new__(app_commands.CommandOnCooldown)
    err.retry_after = 4.0
    await cog.cog_app_command_error(inter, err)
    msg = inter.followup.send.call_args.args[0]
    assert "⏳" in msg
