import contextlib
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

import app.bot.cogs.subscription as sub_mod
from app.bot.cogs.subscription import SubscriptionCog


def _patch_scope(monkeypatch, repo):
    @contextlib.asynccontextmanager
    async def fake_scope():
        yield MagicMock()

    monkeypatch.setattr(sub_mod, "session_scope", fake_scope)
    monkeypatch.setattr(sub_mod, "SubscriptionRepository", lambda session: repo)


@pytest.mark.asyncio
async def test_fire_due_runs_only_due_and_marks(monkeypatch):
    from zoneinfo import ZoneInfo

    today = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    due = SimpleNamespace(id=1, hour=0, minute=0, last_run_on=None)  # luôn tới giờ
    notdue = SimpleNamespace(id=2, hour=0, minute=0, last_run_on=today)  # đã chạy hôm nay
    repo = MagicMock()
    repo.active_all = AsyncMock(return_value=[due, notdue])
    repo.mark_ran = AsyncMock()
    _patch_scope(monkeypatch, repo)

    cog = SubscriptionCog(MagicMock(), MagicMock())
    cog._run = AsyncMock()
    await cog._fire_due(datetime.now(UTC))

    cog._run.assert_awaited_once()  # chỉ cái due
    repo.mark_ran.assert_awaited_once_with(1, ANY)


@pytest.mark.asyncio
async def test_run_posts_digest(monkeypatch):
    ch = SimpleNamespace(send=AsyncMock(), guild=SimpleNamespace(id=123))
    bot = MagicMock()
    bot.get_channel = lambda cid: ch
    cog = SubscriptionCog(bot, MagicMock())
    sub = SimpleNamespace(id=1, channel_id=10, guild_id="pk", topic="chứng khoán")

    cfg = SimpleNamespace(enabled=True, persona="")
    monkeypatch.setattr(
        sub_mod, "AIConfigRepository", lambda s: SimpleNamespace(get=AsyncMock(return_value=cfg))
    )
    monkeypatch.setattr(sub_mod, "run_web_search", AsyncMock(return_value="VN-Index tăng 1%..."))
    gw = SimpleNamespace(complete=AsyncMock(return_value="📊 Chứng khoán hôm nay tăng"))
    monkeypatch.setattr(sub_mod, "_gateway", lambda s: gw)

    await cog._run(sub, MagicMock())

    ch.send.assert_awaited_once()
    assert "Chứng khoán hôm nay" in ch.send.call_args.args[0]


@pytest.mark.asyncio
async def test_run_skips_when_websearch_fails(monkeypatch):
    ch = SimpleNamespace(send=AsyncMock(), guild=SimpleNamespace(id=123))
    bot = MagicMock()
    bot.get_channel = lambda cid: ch
    cog = SubscriptionCog(bot, MagicMock())
    sub = SimpleNamespace(id=1, channel_id=10, guild_id="pk", topic="x")

    cfg = SimpleNamespace(enabled=True, persona="")
    monkeypatch.setattr(
        sub_mod, "AIConfigRepository", lambda s: SimpleNamespace(get=AsyncMock(return_value=cfg))
    )
    monkeypatch.setattr(sub_mod, "run_web_search", AsyncMock(return_value="Tra web thất bại."))
    await cog._run(sub, MagicMock())
    ch.send.assert_not_awaited()  # web hỏng -> không đăng
