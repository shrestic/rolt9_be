"""Unit tests for the BadgesCog slash command.

We monkey-patch `session_scope` and `_build_service` in the cog module so each
test gets a fully-controlled stub service without touching the DB. The command
is exercised by calling `.callback(cog, interaction, ...)` directly — discord.py
wraps the coroutine in an `app_commands.Command` object but preserves the
original coroutine as `.callback`.
"""

import contextlib
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.bot.cogs.badges as badges_mod
from app.bot.cogs.badges import BadgesCog
from app.services.badges.catalog import by_key


def test_cog_registers_command():
    cog = BadgesCog(MagicMock(), MagicMock())
    names = {c.name for c in cog.get_app_commands()}
    assert "badges" in names


def _patch(monkeypatch, stub):
    @contextlib.asynccontextmanager
    async def fake_scope():
        yield MagicMock()

    monkeypatch.setattr(badges_mod, "session_scope", fake_scope)
    monkeypatch.setattr(badges_mod, "_build_service", lambda session: stub)


def _interaction(user_id=1):
    inter = MagicMock()
    inter.guild_id = 100
    inter.user = SimpleNamespace(id=user_id, mention=f"<@{user_id}>")
    inter.response = SimpleNamespace(defer=AsyncMock())
    inter.followup = SimpleNamespace(send=AsyncMock())
    return inter


@pytest.mark.asyncio
async def test_badges_lists_earned_and_locked(monkeypatch):
    stub = MagicMock()
    stub.list_for = AsyncMock(
        return_value=(
            [(by_key("level_5"), datetime(2026, 5, 1, tzinfo=UTC))],
            [by_key("level_10")],
            True,
        )
    )
    _patch(monkeypatch, stub)
    cog = BadgesCog(MagicMock(), MagicMock())
    inter = _interaction()
    await cog.badges.callback(cog, inter, None)
    msg = inter.followup.send.call_args.args[0]
    assert "Tân binh" in msg  # earned
    assert "Kỳ cựu" in msg  # locked


@pytest.mark.asyncio
async def test_badges_disabled(monkeypatch):
    stub = MagicMock()
    stub.list_for = AsyncMock(return_value=([], [], False))
    _patch(monkeypatch, stub)
    cog = BadgesCog(MagicMock(), MagicMock())
    inter = _interaction()
    await cog.badges.callback(cog, inter, None)
    msg = inter.followup.send.call_args.args[0]
    assert "tắt" in msg
