import contextlib
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.bot.cogs.reminder as reminder_mod
from app.bot.cogs.reminder import ReminderCog


def _patch(monkeypatch, repo):
    @contextlib.asynccontextmanager
    async def fake_scope():
        yield MagicMock()

    monkeypatch.setattr(reminder_mod, "session_scope", fake_scope)
    monkeypatch.setattr(reminder_mod, "ReminderRepository", lambda session: repo)


def _reminder(rid=1, channel_id=10, targets=(1, 2), msg="chơi game"):
    return SimpleNamespace(id=rid, channel_id=channel_id, target_ids=list(targets), message=msg)


@pytest.mark.asyncio
async def test_fire_due_pings_targets_and_marks(monkeypatch):
    ch = SimpleNamespace(send=AsyncMock())
    bot = MagicMock()
    bot.get_channel = lambda cid: ch
    repo = MagicMock()
    repo.due = AsyncMock(return_value=[_reminder()])
    repo.mark_fired = AsyncMock()
    _patch(monkeypatch, repo)

    cog = ReminderCog(bot, MagicMock())
    await cog._fire_due(datetime.now(UTC))

    ch.send.assert_awaited_once()
    sent = ch.send.call_args.args[0]
    assert "<@1>" in sent and "<@2>" in sent and "chơi game" in sent
    repo.mark_fired.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_fire_due_marks_even_if_channel_gone(monkeypatch):
    # kênh đã xoá -> không gửi được nhưng VẪN mark fired để khỏi lặp mỗi phút
    bot = MagicMock()
    bot.get_channel = lambda cid: None
    repo = MagicMock()
    repo.due = AsyncMock(return_value=[_reminder()])
    repo.mark_fired = AsyncMock()
    _patch(monkeypatch, repo)

    cog = ReminderCog(bot, MagicMock())
    await cog._fire_due(datetime.now(UTC))
    repo.mark_fired.assert_awaited_once_with(1)
