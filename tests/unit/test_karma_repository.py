import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models.guild import Guild
from app.repositories.karma import KarmaRepository
from app.repositories.karma_config import KarmaConfigRepository
from app.repositories.karma_grant import KarmaGrantRepository


async def _seed_guild(session, gid):
    session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    await session.commit()


@pytest.mark.asyncio
async def test_add_point_accumulates(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = KarmaRepository(db_session)
    assert await repo.add_point(gid, 7) == 1
    assert await repo.add_point(gid, 7) == 2
    assert (await repo.get(gid, 7)).points == 2


@pytest.mark.asyncio
async def test_leaderboard_and_rank(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = KarmaRepository(db_session)
    for uid, n in [(1, 1), (2, 5), (3, 3)]:
        for _ in range(n):
            await repo.add_point(gid, uid)
    rows, total = await repo.leaderboard(gid, limit=10, offset=0)
    assert total == 3
    assert [r.user_id for r in rows] == [2, 3, 1]
    assert await repo.rank_of(gid, 2) == 1
    assert await repo.rank_of(gid, 1) == 3
    assert await repo.rank_of(gid, 999) is None


@pytest.mark.asyncio
async def test_try_grant_cooldown(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = KarmaGrantRepository(db_session)
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    cutoff = now - timedelta(hours=24)
    assert await repo.try_grant(gid, 1, 2, now=now, cutoff=cutoff) is True
    assert await repo.try_grant(gid, 1, 2, now=now, cutoff=cutoff) is False
    assert await repo.try_grant(gid, 1, 3, now=now, cutoff=cutoff) is True
    later = now + timedelta(hours=25)
    assert await repo.try_grant(gid, 1, 2, now=later, cutoff=later - timedelta(hours=24)) is True


@pytest.mark.asyncio
async def test_config_defaults_disabled(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = KarmaConfigRepository(db_session)
    cfg = await repo.get_or_create(gid)
    assert cfg.enabled is False
    assert (await repo.upsert(gid, {"enabled": True})).enabled is True
