"""Unit tests for MinigameCog — /game flip, taixiu, slots commands.

Tests use monkeypatch to replace `session_scope` and `_build_service` in the
minigame module so no real DB or Discord connection is needed.
"""

import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from discord import app_commands

import app.bot.cogs.minigame as minigame_mod
from app.bot.cogs.minigame import MinigameCog
from app.services.minigames.minigame_service import GameResult


def test_cog_registers_group():
    cog = MinigameCog(MagicMock(), MagicMock())
    names = {c.name for c in cog.get_app_commands()}
    assert "game" in names


def _patch(monkeypatch, stub):
    @contextlib.asynccontextmanager
    async def fake_scope():
        yield MagicMock()

    monkeypatch.setattr(minigame_mod, "session_scope", fake_scope)
    monkeypatch.setattr(minigame_mod, "_build_service", lambda session: stub)


def _interaction(user_id=1):
    inter = MagicMock()
    inter.guild_id = 100
    inter.user = SimpleNamespace(id=user_id, mention=f"<@{user_id}>")
    inter.response = SimpleNamespace(
        defer=AsyncMock(), send_message=AsyncMock(), is_done=MagicMock(return_value=True)
    )
    inter.followup = SimpleNamespace(send=AsyncMock())
    return inter


@pytest.mark.asyncio
async def test_flip_win_reports(monkeypatch):
    stub = MagicMock()
    stub.play_coinflip = AsyncMock(
        return_value=GameResult(won=True, payout=190, net=90, balance=1090, detail="Ngửa")
    )
    _patch(monkeypatch, stub)
    cog = MinigameCog(MagicMock(), MagicMock())
    inter = _interaction()
    await cog.game_flip.callback(cog, inter, 100, "heads")
    msg = inter.followup.send.call_args.args[0]
    assert "1.090" in msg or "1090" in msg or "90" in msg


@pytest.mark.asyncio
async def test_flip_error_friendly(monkeypatch):
    stub = MagicMock()
    stub.play_coinflip = AsyncMock(side_effect=ValueError("Không đủ coin"))
    _patch(monkeypatch, stub)
    cog = MinigameCog(MagicMock(), MagicMock())
    inter = _interaction()
    await cog.game_flip.callback(cog, inter, 100, "heads")
    msg = inter.followup.send.call_args.args[0]
    assert "❌" in msg


@pytest.mark.asyncio
async def test_slots_reports(monkeypatch):
    stub = MagicMock()
    stub.play_slots = AsyncMock(
        return_value=GameResult(won=True, payout=1000, net=900, balance=1900, detail="💎💎💎")
    )
    _patch(monkeypatch, stub)
    cog = MinigameCog(MagicMock(), MagicMock())
    inter = _interaction()
    await cog.game_slots.callback(cog, inter, 100)
    msg = inter.followup.send.call_args.args[0]
    assert "💎💎💎" in msg


@pytest.mark.asyncio
async def test_taixiu_reports(monkeypatch):
    stub = MagicMock()
    stub.play_taixiu = AsyncMock(
        return_value=GameResult(
            won=False, payout=0, net=-100, balance=900, detail="🎲 6+6+6=18 (Tài)"
        )
    )
    _patch(monkeypatch, stub)
    cog = MinigameCog(MagicMock(), MagicMock())
    inter = _interaction()
    await cog.game_taixiu.callback(cog, inter, 100, "xiu")
    msg = inter.followup.send.call_args.args[0]
    assert "Thua" in msg


@pytest.mark.asyncio
async def test_cooldown_error_handled():
    cog = MinigameCog(MagicMock(), MagicMock())
    inter = _interaction()
    # Construct a real CommandOnCooldown instance without calling __init__
    # (its constructor signature varies across discord.py versions).
    # __new__ still produces a proper instance so isinstance() holds.
    err = app_commands.CommandOnCooldown.__new__(app_commands.CommandOnCooldown)
    err.retry_after = 2.5
    await cog.cog_app_command_error(inter, err)
    # is_done() returns True → handler uses followup.send with a ⏳ message
    msg = inter.followup.send.call_args.args[0]
    assert "⏳" in msg
