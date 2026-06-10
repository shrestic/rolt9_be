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


def _reminder(rid=1, channel_id=10, targets=(1, 2), msg="play games"):
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
    assert "<@1>" in sent and "<@2>" in sent and "play games" in sent
    repo.mark_fired.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_fire_due_marks_even_if_channel_gone(monkeypatch):
    # channel was deleted -> can't send but STILL mark fired so it doesn't retry every minute
    bot = MagicMock()
    bot.get_channel = lambda cid: None
    repo = MagicMock()
    repo.due = AsyncMock(return_value=[_reminder()])
    repo.mark_fired = AsyncMock()
    _patch(monkeypatch, repo)

    cog = ReminderCog(bot, MagicMock())
    await cog._fire_due(datetime.now(UTC))
    repo.mark_fired.assert_awaited_once_with(1)


def _smart_reminder(rid=1, channel_id=10, targets=(1,), task="gold price today"):
    # reminder with a `task` -> at fire time it must do a LIVE lookup + AI answer, not echo `message`.
    return SimpleNamespace(
        id=rid,
        channel_id=channel_id,
        target_ids=list(targets),
        message="placeholder",
        task=task,
        guild_id="g-pk",
    )


def _patch_ai(monkeypatch, *, web_result, ai_result, enabled=True, persona="rolt9"):
    """Fake run_web_search + AIConfigRepository + _gateway for the smart reminder."""
    monkeypatch.setattr(reminder_mod, "run_web_search", AsyncMock(return_value=web_result))
    cfg = SimpleNamespace(enabled=enabled, persona=persona)
    monkeypatch.setattr(
        reminder_mod,
        "AIConfigRepository",
        lambda s: SimpleNamespace(get=AsyncMock(return_value=cfg)),
    )
    gw = SimpleNamespace(complete=AsyncMock(return_value=ai_result))
    monkeypatch.setattr(reminder_mod, "_gateway", lambda s: gw)
    return gw


@pytest.mark.asyncio
async def test_fire_due_smart_task_websearch_then_ai_posts_live(monkeypatch):
    # Smart reminder: at fire time -> web search + AI gives a REAL answer (gold price), does NOT echo the static message.
    ch = SimpleNamespace(send=AsyncMock(), guild=SimpleNamespace(id=999))
    bot = MagicMock()
    bot.get_channel = lambda cid: ch
    repo = MagicMock()
    repo.due = AsyncMock(return_value=[_smart_reminder()])
    repo.mark_fired = AsyncMock()
    _patch(monkeypatch, repo)
    gw = _patch_ai(
        monkeypatch,
        web_result="SJC quoted at 80 million/tael this morning...",
        ai_result="SJC gold 80M/tael 💰",
    )

    cog = ReminderCog(bot, MagicMock())
    await cog._fire_due(datetime.now(UTC))

    sent = ch.send.call_args.args[0]
    assert "SJC gold 80M" in sent  # REAL content from the AI
    assert "placeholder" not in sent  # does NOT echo the static message
    assert "It's time:" not in sent  # takes the smart branch, not the plain branch
    assert "<@1>" in sent  # still pings the person who set the reminder
    reminder_mod.run_web_search.assert_awaited_once_with("gold price today")
    gw.complete.assert_awaited_once()
    repo.mark_fired.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_fire_due_smart_task_fetch_fails_fallback_still_marks(monkeypatch):
    # Web lookup failed -> still announce (fallback), do NOT go silent, and STILL mark fired.
    ch = SimpleNamespace(send=AsyncMock(), guild=SimpleNamespace(id=999))
    bot = MagicMock()
    bot.get_channel = lambda cid: ch
    repo = MagicMock()
    repo.due = AsyncMock(return_value=[_smart_reminder(rid=7)])
    repo.mark_fired = AsyncMock()
    _patch(monkeypatch, repo)
    # NOTE: "failed" is one of the failure sentinels _run_task checks for in the
    # run_web_search result ("Web search failed.") — keep it so the fallback path triggers.
    _patch_ai(monkeypatch, web_result="Web search failed.", ai_result="(should not reach here)")

    cog = ReminderCog(bot, MagicMock())
    await cog._fire_due(datetime.now(UTC))

    sent = ch.send.call_args.args[0]
    assert "couldn't dig anything up" in sent  # fallback line
    repo.mark_fired.assert_awaited_once_with(7)
