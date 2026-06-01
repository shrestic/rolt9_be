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


def _smart_reminder(rid=1, channel_id=10, targets=(1,), task="giá vàng hôm nay"):
    # reminder có `task` -> tới giờ phải TRA SỐNG + AI trả lời, không echo `message`.
    return SimpleNamespace(
        id=rid,
        channel_id=channel_id,
        target_ids=list(targets),
        message="placeholder",
        task=task,
        guild_id="g-pk",
    )


def _patch_ai(monkeypatch, *, web_result, ai_result, enabled=True, persona="rolt9"):
    """Giả run_web_search + AIConfigRepository + _gateway cho smart reminder."""
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
    # Smart reminder: tới giờ -> web search + AI trả lời THẬT (giá vàng), KHÔNG echo message tĩnh.
    ch = SimpleNamespace(send=AsyncMock(), guild=SimpleNamespace(id=999))
    bot = MagicMock()
    bot.get_channel = lambda cid: ch
    repo = MagicMock()
    repo.due = AsyncMock(return_value=[_smart_reminder()])
    repo.mark_fired = AsyncMock()
    _patch(monkeypatch, repo)
    gw = _patch_ai(
        monkeypatch,
        web_result="SJC niêm yết 80 triệu/lượng sáng nay...",
        ai_result="Vàng SJC 80tr/lượng nha 💰",
    )

    cog = ReminderCog(bot, MagicMock())
    await cog._fire_due(datetime.now(UTC))

    sent = ch.send.call_args.args[0]
    assert "Vàng SJC 80tr" in sent  # nội dung THẬT từ AI
    assert "placeholder" not in sent  # KHÔNG echo message tĩnh
    assert "Tới giờ rồi nè" not in sent  # đi nhánh smart, không nhánh thường
    assert "<@1>" in sent  # vẫn ping người hẹn
    reminder_mod.run_web_search.assert_awaited_once_with("giá vàng hôm nay")
    gw.complete.assert_awaited_once()
    repo.mark_fired.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_fire_due_smart_task_fetch_fails_fallback_still_marks(monkeypatch):
    # Tra web hỏng -> vẫn báo (fallback), KHÔNG im lặng, và VẪN mark fired.
    ch = SimpleNamespace(send=AsyncMock(), guild=SimpleNamespace(id=999))
    bot = MagicMock()
    bot.get_channel = lambda cid: ch
    repo = MagicMock()
    repo.due = AsyncMock(return_value=[_smart_reminder(rid=7)])
    repo.mark_fired = AsyncMock()
    _patch(monkeypatch, repo)
    _patch_ai(monkeypatch, web_result="Tìm web thất bại.", ai_result="(không tới đây)")

    cog = ReminderCog(bot, MagicMock())
    await cog._fire_due(datetime.now(UTC))

    sent = ch.send.call_args.args[0]
    assert "tra không ra" in sent  # câu fallback
    repo.mark_fired.assert_awaited_once_with(7)
