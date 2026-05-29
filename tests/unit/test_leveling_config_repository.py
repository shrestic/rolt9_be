import uuid

import pytest

from app.models.guild import Guild
from app.repositories.leveling_config import GuildLevelingConfigRepository


async def _seed_guild(session, gid):
    session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    await session.commit()


@pytest.mark.asyncio
async def test_get_returns_none_when_missing(db_session):
    repo = GuildLevelingConfigRepository(db_session)
    assert await repo.get(uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_get_or_create_creates_defaults_first_time(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)

    repo = GuildLevelingConfigRepository(db_session)
    cfg = await repo.get_or_create(gid)
    assert cfg.enabled is False
    assert cfg.xp_min == 15
    assert cfg.xp_max == 25
    assert cfg.notification_mode == "channel"


@pytest.mark.asyncio
async def test_get_or_create_is_idempotent(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)

    repo = GuildLevelingConfigRepository(db_session)
    a = await repo.get_or_create(gid)
    b = await repo.get_or_create(gid)
    assert a.guild_id == b.guild_id


@pytest.mark.asyncio
async def test_upsert_updates_existing(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)

    repo = GuildLevelingConfigRepository(db_session)
    await repo.get_or_create(gid)
    updated = await repo.upsert(
        gid,
        {"enabled": True, "xp_min": 5, "xp_max": 10, "notification_mode": "dm"},
    )
    assert updated.enabled is True
    assert updated.xp_min == 5
    assert updated.xp_max == 10
    assert updated.notification_mode == "dm"
