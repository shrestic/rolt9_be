import uuid

import pytest
from sqlalchemy import select

from app.bot.cache.leveling_config_cache import CachedLevelingConfig, LevelingConfigCache
from app.models.guild import Guild
from app.models.guild_leveling_config import GuildLevelingConfig


@pytest.fixture
def session_factory(db_session):
    # Bridge: tests use the conftest-provided db_session, but cache code expects
    # a "session_factory" callable returning an async context manager.
    class _F:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *a):
            pass

    def factory():
        return _F()

    return factory


@pytest.mark.asyncio
async def test_cache_miss_loads_from_db(db_session, session_factory):
    gid = uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=10, name="g", icon_url=None, is_active=True))
    db_session.add(GuildLevelingConfig(guild_id=gid, enabled=True))
    await db_session.commit()

    cache = LevelingConfigCache(session_factory=session_factory)
    cfg = await cache.get(10)
    assert isinstance(cfg, CachedLevelingConfig)
    assert cfg.enabled is True


@pytest.mark.asyncio
async def test_cache_returns_none_for_unknown_guild(db_session, session_factory):
    cache = LevelingConfigCache(session_factory=session_factory)
    assert await cache.get(99999) is None


@pytest.mark.asyncio
async def test_invalidate_forces_reload(db_session, session_factory):
    gid = uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=10, name="g", icon_url=None, is_active=True))
    db_session.add(GuildLevelingConfig(guild_id=gid, enabled=False))
    await db_session.commit()

    cache = LevelingConfigCache(session_factory=session_factory)
    first = await cache.get(10)
    assert first.enabled is False

    cfg = (
        await db_session.execute(
            select(GuildLevelingConfig).where(GuildLevelingConfig.guild_id == gid)
        )
    ).scalar_one()
    cfg.enabled = True
    await db_session.commit()

    # Without invalidate, stale value.
    assert (await cache.get(10)).enabled is False
    cache.invalidate(10)
    assert (await cache.get(10)).enabled is True
