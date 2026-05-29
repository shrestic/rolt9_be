import uuid

import pytest

from app.models.guild import Guild
from app.repositories.badge_config import BadgeConfigRepository
from app.repositories.user_badge import BadgeRepository


async def _seed_guild(session, gid):
    session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    await session.commit()


@pytest.mark.asyncio
async def test_add_is_idempotent(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = BadgeRepository(db_session)
    assert await repo.add(gid, 7, "level_5") is True
    assert await repo.add(gid, 7, "level_5") is False  # already held
    assert await repo.earned_keys(gid, 7) == {"level_5"}


@pytest.mark.asyncio
async def test_earned_keys_and_list(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = BadgeRepository(db_session)
    await repo.add(gid, 7, "level_5")
    await repo.add(gid, 7, "streak_7")
    assert await repo.earned_keys(gid, 7) == {"level_5", "streak_7"}
    rows = await repo.list_earned(gid, 7)
    assert {r.badge_key for r in rows} == {"level_5", "streak_7"}
    assert all(r.earned_at is not None for r in rows)


@pytest.mark.asyncio
async def test_config_get_or_create_defaults_disabled(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = BadgeConfigRepository(db_session)
    cfg = await repo.get_or_create(gid)
    assert cfg.enabled is False
    updated = await repo.upsert(gid, {"enabled": True})
    assert updated.enabled is True
