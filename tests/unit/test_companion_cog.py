import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

import app.bot.cogs.companion as companion_mod
from app.bot.cogs.companion import CompanionCog


class _AsyncIter:
    def __init__(self, items):
        self._items = items

    def __aiter__(self):
        async def gen():
            for x in self._items:
                yield x

        return gen()


def _channel(history_items=()):
    return SimpleNamespace(
        id=10, send=AsyncMock(), history=lambda limit: _AsyncIter(list(history_items))
    )


def _member(name, game=None):
    acts = [SimpleNamespace(type=discord.ActivityType.playing, name=game)] if game else []
    return SimpleNamespace(id=hash(name) % 9999, bot=False, display_name=name, activities=acts)


def _guild(channel, members=()):
    return SimpleNamespace(
        id=100, get_channel=lambda cid: channel, members=list(members), voice_channels=[]
    )


def _cfg(**kw):
    base = {
        "enabled": True,
        "companion_enabled": True,
        "companion_channel_id": 10,
        "companion_cooldown_min": 45,
        "persona": "",
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _patch(monkeypatch, stub):
    @contextlib.asynccontextmanager
    async def fake_scope():
        yield MagicMock()

    monkeypatch.setattr(companion_mod, "session_scope", fake_scope)
    monkeypatch.setattr(companion_mod, "_build_service", lambda session: stub)


def _cog(cfg):
    bot = MagicMock()
    bot.user = SimpleNamespace(id=1)
    cog = CompanionCog(bot, MagicMock())
    cog._load_cfg = AsyncMock(return_value=cfg)
    return cog


@pytest.mark.asyncio
async def test_handle_guild_posts_when_activity(monkeypatch):
    stub = MagicMock()
    stub.decide = AsyncMock(return_value="Ê An chơi LoL một mình kìa 👀")
    _patch(monkeypatch, stub)
    cog = _cog(_cfg())
    ch = _channel()
    guild = _guild(ch, members=[_member("An", game="LoL")])
    await cog._handle_guild(guild, now=10_000.0)
    stub.decide.assert_awaited_once()
    ch.send.assert_awaited_once()
    assert cog.cooldown[100] == 10_000.0


@pytest.mark.asyncio
async def test_handle_guild_skip_when_disabled(monkeypatch):
    stub = MagicMock()
    stub.decide = AsyncMock()
    _patch(monkeypatch, stub)
    cog = _cog(_cfg(companion_enabled=False))
    ch = _channel()
    await cog._handle_guild(_guild(ch, members=[_member("An", game="LoL")]), now=10_000.0)
    stub.decide.assert_not_awaited()
    ch.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_guild_skip_no_activity(monkeypatch):
    stub = MagicMock()
    stub.decide = AsyncMock()
    _patch(monkeypatch, stub)
    cog = _cog(_cfg())
    ch = _channel()  # no history, no members -> snapshot None
    await cog._handle_guild(_guild(ch, members=[]), now=10_000.0)
    stub.decide.assert_not_awaited()  # KHÔNG gọi AI khi không có gì


@pytest.mark.asyncio
async def test_handle_guild_cooldown_blocks(monkeypatch):
    stub = MagicMock()
    stub.decide = AsyncMock(return_value="hi")
    _patch(monkeypatch, stub)
    cog = _cog(_cfg(companion_cooldown_min=45))
    cog.cooldown[100] = 10_000.0  # vừa nói
    ch = _channel()
    await cog._handle_guild(_guild(ch, members=[_member("An", game="LoL")]), now=10_000.0 + 60)
    stub.decide.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_guild_skip_silenced(monkeypatch):
    stub = MagicMock()
    stub.decide = AsyncMock(return_value=None)  # AI chọn SKIP
    _patch(monkeypatch, stub)
    cog = _cog(_cfg())
    ch = _channel()
    await cog._handle_guild(_guild(ch, members=[_member("An", game="LoL")]), now=10_000.0)
    ch.send.assert_not_awaited()
    assert 100 not in cog.cooldown
