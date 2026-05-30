"""Unit tests for the /pet cog.

Patches session_scope + _build_service so no DB or Discord is needed.
Covers: status render, status-disabled, feed success, feed ValueError,
play with level-up + evolution.
"""

import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.bot.cogs.pet as pet_mod
from app.bot.cogs.pet import PetCog
from app.services.pet.pet_service import PetActionResult, PetStatus


def test_cog_registers_group():
    cog = PetCog(MagicMock(), MagicMock())
    names = {c.name for c in cog.get_app_commands()}
    assert "pet" in names


def _patch(monkeypatch, stub):
    @contextlib.asynccontextmanager
    async def fake_scope():
        yield MagicMock()

    monkeypatch.setattr(pet_mod, "session_scope", fake_scope)
    monkeypatch.setattr(pet_mod, "_build_service", lambda session: stub)


def _interaction(user_id=1):
    inter = MagicMock()
    inter.guild_id = 100
    inter.user = SimpleNamespace(id=user_id, mention=f"<@{user_id}>")
    inter.response = SimpleNamespace(defer=AsyncMock())
    inter.followup = SimpleNamespace(send=AsyncMock())
    return inter


def _status(**over):
    base = {
        "name": "Rex",
        "hunger": 60,
        "happiness": 40,
        "xp": 20,
        "level": 1,
        "stage_name": "Trứng",
        "stage_emoji": "🥚",
        "mood_emoji": "🙂",
        "enabled": True,
    }
    base.update(over)
    return PetStatus(**base)


@pytest.mark.asyncio
async def test_pet_status_renders(monkeypatch):
    stub = MagicMock()
    stub.get_status = AsyncMock(return_value=_status())
    _patch(monkeypatch, stub)
    cog = PetCog(MagicMock(), MagicMock())
    inter = _interaction()
    await cog.pet_status.callback(cog, inter)
    msg = inter.followup.send.call_args.args[0]
    assert "Rex" in msg
    assert "60" in msg


@pytest.mark.asyncio
async def test_pet_status_disabled(monkeypatch):
    stub = MagicMock()
    stub.get_status = AsyncMock(return_value=_status(enabled=False))
    _patch(monkeypatch, stub)
    cog = PetCog(MagicMock(), MagicMock())
    inter = _interaction()
    await cog.pet_status.callback(cog, inter)
    msg = inter.followup.send.call_args.args[0]
    assert "chưa" in msg.lower()


@pytest.mark.asyncio
async def test_pet_feed_reports(monkeypatch):
    stub = MagicMock()
    stub.feed = AsyncMock(
        return_value=PetActionResult(
            status=_status(hunger=90), leveled_up=False, evolved=False, balance=90
        )
    )
    _patch(monkeypatch, stub)
    cog = PetCog(MagicMock(), MagicMock())
    inter = _interaction()
    await cog.pet_feed.callback(cog, inter)
    msg = inter.followup.send.call_args.args[0]
    assert "90" in msg


@pytest.mark.asyncio
async def test_pet_feed_error_is_friendly(monkeypatch):
    stub = MagicMock()
    stub.feed = AsyncMock(side_effect=ValueError("Không đủ coin"))
    _patch(monkeypatch, stub)
    cog = PetCog(MagicMock(), MagicMock())
    inter = _interaction()
    await cog.pet_feed.callback(cog, inter)
    msg = inter.followup.send.call_args.args[0]
    assert "❌" in msg


@pytest.mark.asyncio
async def test_pet_play_reports_evolution(monkeypatch):
    stub = MagicMock()
    stub.play = AsyncMock(
        return_value=PetActionResult(
            status=_status(happiness=70, level=5, stage_name="Non", stage_emoji="🐣"),
            leveled_up=True,
            evolved=True,
            balance=-1,
        )
    )
    _patch(monkeypatch, stub)
    cog = PetCog(MagicMock(), MagicMock())
    inter = _interaction()
    await cog.pet_play.callback(cog, inter)
    msg = inter.followup.send.call_args.args[0]
    assert "tiến hóa" in msg.lower() or "Non" in msg
