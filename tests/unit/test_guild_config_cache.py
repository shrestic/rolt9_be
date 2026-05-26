import contextlib

import pytest

from app.bot.cache.guild_config_cache import GuildConfigCache
from app.repositories.custom_command import CustomCommandRepository
from app.repositories.guild import GuildRepository
from app.repositories.guild_settings import GuildSettingsRepository


def _factory_for(session):
    @contextlib.asynccontextmanager
    async def _factory():
        yield session

    return _factory


@pytest.mark.asyncio
async def test_load_returns_config_with_commands(db_session):
    g = await GuildRepository(db_session).upsert(discord_id=1, name="g", icon_url=None)
    await GuildSettingsRepository(db_session).update_section(
        g.id, "commands", {"prefix": "?", "enabled": True}
    )
    await CustomCommandRepository(db_session).create(
        guild_id=g.id, data={"trigger": "hi", "response_type": "text", "response_text": "yo"}
    )
    cache = GuildConfigCache(session_factory=_factory_for(db_session))
    cfg = await cache.get(1)
    assert cfg is not None
    assert cfg.prefix == "?"
    assert len(cfg.commands) == 1
    assert cfg.commands[0].trigger == "hi"


@pytest.mark.asyncio
async def test_unknown_guild_returns_none(db_session):
    cache = GuildConfigCache(session_factory=_factory_for(db_session))
    assert await cache.get(999) is None


@pytest.mark.asyncio
async def test_cache_hit_does_not_reload(db_session):
    g = await GuildRepository(db_session).upsert(discord_id=1, name="g", icon_url=None)
    await GuildSettingsRepository(db_session).create_defaults(g.id)
    cache = GuildConfigCache(session_factory=_factory_for(db_session), ttl=1000)
    calls = {"n": 0}
    original = cache._load

    async def counting(gid):
        calls["n"] += 1
        return await original(gid)

    cache._load = counting
    await cache.get(1)
    await cache.get(1)
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_invalidate_forces_reload(db_session):
    g = await GuildRepository(db_session).upsert(discord_id=1, name="g", icon_url=None)
    await GuildSettingsRepository(db_session).create_defaults(g.id)
    cache = GuildConfigCache(session_factory=_factory_for(db_session), ttl=1000)
    calls = {"n": 0}
    original = cache._load

    async def counting(gid):
        calls["n"] += 1
        return await original(gid)

    cache._load = counting
    await cache.get(1)
    cache.invalidate(1)
    await cache.get(1)
    assert calls["n"] == 2
