import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.bot.cogs.quests as quests_mod
from app.bot.cogs.quests import QuestsCog
from app.services.quests.quest_service import ClaimResult, QuestView


def test_cog_registers_group():
    cog = QuestsCog(MagicMock(), MagicMock())
    names = {c.name for c in cog.get_app_commands()}
    assert "quests" in names


def _patch(monkeypatch, stub):
    @contextlib.asynccontextmanager
    async def fake_scope():
        yield MagicMock()

    monkeypatch.setattr(quests_mod, "session_scope", fake_scope)
    monkeypatch.setattr(quests_mod, "_build_service", lambda session: stub)


def _interaction(user_id=1):
    inter = MagicMock()
    inter.guild_id = 100
    inter.user = SimpleNamespace(id=user_id, mention=f"<@{user_id}>")
    inter.response = SimpleNamespace(defer=AsyncMock())
    inter.followup = SimpleNamespace(send=AsyncMock())
    return inter


def _view(name, progress, target, claimed=False):
    q = SimpleNamespace(name=name, target=target, reward_coins=50, period="daily")
    return QuestView(
        quest=q, progress=progress, target=target, completed=progress >= target, claimed=claimed
    )


@pytest.mark.asyncio
async def test_quests_list_renders(monkeypatch):
    stub = MagicMock()
    stub.list_quests = AsyncMock(return_value=[_view("Earn 100", 40, 100)])
    _patch(monkeypatch, stub)
    cog = QuestsCog(MagicMock(), MagicMock())
    inter = _interaction()
    await cog.quests_list.callback(cog, inter)
    msg = inter.followup.send.call_args.args[0]
    assert "Earn 100" in msg
    assert "40/100" in msg


@pytest.mark.asyncio
async def test_quests_claim_reports_total(monkeypatch):
    stub = MagicMock()
    stub.claim = AsyncMock(
        return_value=ClaimResult(claimed_count=2, total_coins=150, names=["A", "B"])
    )
    _patch(monkeypatch, stub)
    cog = QuestsCog(MagicMock(), MagicMock())
    inter = _interaction()
    await cog.quests_claim.callback(cog, inter)
    msg = inter.followup.send.call_args.args[0]
    assert "150" in msg


@pytest.mark.asyncio
async def test_quests_claim_nothing(monkeypatch):
    stub = MagicMock()
    stub.claim = AsyncMock(return_value=ClaimResult(claimed_count=0, total_coins=0, names=[]))
    _patch(monkeypatch, stub)
    cog = QuestsCog(MagicMock(), MagicMock())
    inter = _interaction()
    await cog.quests_claim.callback(cog, inter)
    msg = inter.followup.send.call_args.args[0]
    assert "Chưa" in msg or "chưa" in msg
