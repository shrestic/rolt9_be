"""Unit tests for the CurrencyCog slash commands.

We monkey-patch `session_scope` and `_build_service` in the cog module so each
test gets a fully-controlled stub service without touching the DB. Commands are
exercised by calling `.callback(cog, interaction, ...)` directly — discord.py
wraps the coroutine in an `app_commands.Command` object but preserves the
original coroutine as `.callback`.
"""

import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.bot.cogs.currency as currency_mod
from app.bot.cogs.currency import CurrencyCog
from app.services.currency.currency_service import DailyResult, StreakInfo


def test_cog_registers_commands():
    cog = CurrencyCog(MagicMock(), MagicMock())
    names = {c.name for c in cog.get_app_commands()}
    # /balance, /daily, /pay, /baltop, /streak, and the /eco group
    assert {"balance", "daily", "pay", "baltop", "streak", "eco"} <= names


def _patch_service(monkeypatch, stub):
    """Make the cog use `stub` as its service and a no-op session scope.

    Also patches `_label` to return a fixed coin emoji so tests don't need a
    real guild/config in the DB.
    """

    @contextlib.asynccontextmanager
    async def fake_scope():
        yield MagicMock()

    monkeypatch.setattr(currency_mod, "session_scope", fake_scope)
    monkeypatch.setattr(currency_mod, "_build_service", lambda session: stub)
    # _label reads the emoji off the service; stub it to a fixed coin.
    monkeypatch.setattr(currency_mod, "_label", AsyncMock(return_value="🪙"))


def _fake_interaction(user_id=1):
    """Build a minimal discord.Interaction-like object for callback tests."""
    inter = MagicMock()
    inter.guild_id = 100
    inter.user = SimpleNamespace(id=user_id, mention=f"<@{user_id}>")
    inter.response = SimpleNamespace(defer=AsyncMock())
    inter.followup = SimpleNamespace(send=AsyncMock())
    return inter


# ---------------------------------------------------------------------------
# /daily — streak-aware reply
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_reply_mentions_streak(monkeypatch):
    """When streak_bonus > 0, reply must contain 'Chuỗi' and the day count."""
    stub = MagicMock()
    stub.claim_daily = AsyncMock(
        return_value=DailyResult(
            claimed=True,
            amount=130,
            base=100,
            streak_bonus=30,
            milestone_bonus=0,
            balance=130,
            streak=3,
            days_to_milestone=4,
            retry_after_seconds=0,
        )
    )
    _patch_service(monkeypatch, stub)
    cog = CurrencyCog(MagicMock(), MagicMock())
    inter = _fake_interaction()
    await cog.daily.callback(cog, inter)
    msg = inter.followup.send.call_args.args[0]
    assert "Chuỗi" in msg
    assert "3" in msg


@pytest.mark.asyncio
async def test_daily_reply_shows_milestone(monkeypatch):
    """When milestone_bonus > 0, reply must contain 'Mốc' and the bonus amount."""
    stub = MagicMock()
    stub.claim_daily = AsyncMock(
        return_value=DailyResult(
            claimed=True,
            amount=370,
            base=100,
            streak_bonus=70,
            milestone_bonus=200,
            balance=370,
            streak=7,
            days_to_milestone=23,
            retry_after_seconds=0,
        )
    )
    _patch_service(monkeypatch, stub)
    cog = CurrencyCog(MagicMock(), MagicMock())
    inter = _fake_interaction()
    await cog.daily.callback(cog, inter)
    msg = inter.followup.send.call_args.args[0]
    assert "Mốc" in msg
    assert "200" in msg


# ---------------------------------------------------------------------------
# /streak command
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_streak_command_renders_current_and_longest(monkeypatch):
    """Normal active streak: reply shows both current and longest values."""
    stub = MagicMock()
    stub.get_streak = AsyncMock(
        return_value=StreakInfo(current=3, longest=9, days_to_milestone=4, enabled=True)
    )
    _patch_service(monkeypatch, stub)
    cog = CurrencyCog(MagicMock(), MagicMock())
    inter = _fake_interaction()
    await cog.streak.callback(cog, inter, None)
    msg = inter.followup.send.call_args.args[0]
    assert "3" in msg
    assert "9" in msg


@pytest.mark.asyncio
async def test_streak_command_disabled(monkeypatch):
    """When streak feature is disabled on the server, reply must contain 'tắt'."""
    stub = MagicMock()
    stub.get_streak = AsyncMock(
        return_value=StreakInfo(current=0, longest=0, days_to_milestone=None, enabled=False)
    )
    _patch_service(monkeypatch, stub)
    cog = CurrencyCog(MagicMock(), MagicMock())
    inter = _fake_interaction()
    await cog.streak.callback(cog, inter, None)
    msg = inter.followup.send.call_args.args[0]
    assert "tắt" in msg
