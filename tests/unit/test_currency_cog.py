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
    real guild/config in the DB.  A default no-op badge service is installed so
    tests that don't care about badges don't see spurious DB calls — individual
    tests can override `_build_badge_service` afterwards.
    """

    @contextlib.asynccontextmanager
    async def fake_scope():
        yield MagicMock()

    monkeypatch.setattr(currency_mod, "session_scope", fake_scope)
    monkeypatch.setattr(currency_mod, "_build_service", lambda session: stub)
    # _label reads the emoji off the service; stub it to a fixed coin.
    monkeypatch.setattr(currency_mod, "_label", AsyncMock(return_value="🪙"))
    # Default badge service returns no new badges — tests that care about
    # badge announcements should override this with their own stub.
    _noop_badge = MagicMock()
    _noop_badge.award_new = AsyncMock(return_value=[])
    monkeypatch.setattr(currency_mod, "_build_badge_service", lambda session: _noop_badge)
    # Default quest service is a silent no-op — tests that care about quest
    # progress should override _build_quest_service with their own stub.
    _noop_quest = MagicMock()
    _noop_quest.record_event = AsyncMock()
    monkeypatch.setattr(currency_mod, "_build_quest_service", lambda session: _noop_quest)


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
    """When streak_bonus > 0, reply must contain 'streak' and the day count."""
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
    assert "streak" in msg
    assert "3" in msg


@pytest.mark.asyncio
async def test_daily_reply_shows_milestone(monkeypatch):
    """When milestone_bonus > 0, reply must contain 'milestone' and the bonus amount."""
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
    assert "milestone" in msg
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
    """When streak feature is disabled on the server, reply must contain 'off'."""
    stub = MagicMock()
    stub.get_streak = AsyncMock(
        return_value=StreakInfo(current=0, longest=0, days_to_milestone=None, enabled=False)
    )
    _patch_service(monkeypatch, stub)
    cog = CurrencyCog(MagicMock(), MagicMock())
    inter = _fake_interaction()
    await cog.streak.callback(cog, inter, None)
    msg = inter.followup.send.call_args.args[0]
    assert "off" in msg


# ---------------------------------------------------------------------------
# /daily — badge announcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_appends_new_badge(monkeypatch):
    """When /daily unlocks a new badge, the reply must contain the badge name."""
    from app.services.badges.catalog import by_key

    stub = MagicMock()
    stub.claim_daily = AsyncMock(
        return_value=DailyResult(
            claimed=True,
            amount=110,
            base=100,
            streak_bonus=10,
            milestone_bonus=0,
            balance=110,
            streak=1,
            days_to_milestone=6,
            retry_after_seconds=0,
        )
    )
    badge_stub = MagicMock()
    badge_stub.award_new = AsyncMock(return_value=[by_key("wealth_1k")])
    _patch_service(monkeypatch, stub)
    monkeypatch.setattr(currency_mod, "_build_badge_service", lambda session: badge_stub)
    cog = CurrencyCog(MagicMock(), MagicMock())
    inter = _fake_interaction()
    await cog.daily.callback(cog, inter)
    msg = inter.followup.send.call_args.args[0]
    assert "Flush" in msg  # the new badge name


# ---------------------------------------------------------------------------
# /daily — quest progress
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_records_quest_progress(monkeypatch):
    """After a successful /daily, both earn_coins and daily_claim events are recorded."""
    stub = MagicMock()
    stub.claim_daily = AsyncMock(
        return_value=DailyResult(
            claimed=True,
            amount=110,
            base=100,
            streak_bonus=10,
            milestone_bonus=0,
            balance=110,
            streak=1,
            days_to_milestone=6,
            retry_after_seconds=0,
        )
    )
    badge_stub = MagicMock()
    badge_stub.award_new = AsyncMock(return_value=[])
    quest_stub = MagicMock()
    quest_stub.record_event = AsyncMock()
    _patch_service(monkeypatch, stub)
    monkeypatch.setattr(currency_mod, "_build_badge_service", lambda session: badge_stub)
    monkeypatch.setattr(currency_mod, "_build_quest_service", lambda session: quest_stub)
    cog = CurrencyCog(MagicMock(), MagicMock())
    inter = _fake_interaction()
    await cog.daily.callback(cog, inter)
    objectives = {c.kwargs["objective_type"] for c in quest_stub.record_event.call_args_list}
    assert objectives == {"earn_coins", "daily_claim"}
