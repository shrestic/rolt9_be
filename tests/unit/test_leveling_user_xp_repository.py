import uuid

import pytest
from sqlalchemy import func, select

from app.models.guild import Guild
from app.models.user_xp import UserXp
from app.repositories.user_xp import UserXpRepository


async def _seed_guild(session, gid):
    session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    await session.commit()


@pytest.mark.asyncio
async def test_get_or_create_creates_zero_row(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = UserXpRepository(db_session)

    row = await repo.get_or_create(gid, user_id=42)
    assert row.total_xp == 0
    assert row.last_xp_at is None


@pytest.mark.asyncio
async def test_get_or_create_is_idempotent(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = UserXpRepository(db_session)

    a = await repo.get_or_create(gid, user_id=42)
    b = await repo.get_or_create(gid, user_id=42)
    assert a.id == b.id


@pytest.mark.asyncio
async def test_set_xp_persists_value(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = UserXpRepository(db_session)

    await repo.get_or_create(gid, user_id=42)
    await repo.set_xp(gid, user_id=42, total_xp=1000)
    row = await repo.get_or_create(gid, user_id=42)
    assert row.total_xp == 1000


@pytest.mark.asyncio
async def test_delete_removes_row(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = UserXpRepository(db_session)

    await repo.get_or_create(gid, user_id=42)
    await repo.delete(gid, user_id=42)
    r = await db_session.execute(select(func.count()).select_from(UserXp))
    assert r.scalar_one() == 0


@pytest.mark.asyncio
async def test_leaderboard_orders_by_total_xp_desc(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = UserXpRepository(db_session)

    for uid, xp in [(1, 100), (2, 500), (3, 200), (4, 800)]:
        await repo.get_or_create(gid, user_id=uid)
        await repo.set_xp(gid, user_id=uid, total_xp=xp)

    rows, total = await repo.leaderboard(gid, limit=10, offset=0)
    assert total == 4
    assert [r.user_id for r in rows] == [4, 2, 3, 1]


@pytest.mark.asyncio
async def test_leaderboard_pagination_offset(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = UserXpRepository(db_session)

    for uid, xp in [(1, 100), (2, 500), (3, 200), (4, 800)]:
        await repo.get_or_create(gid, user_id=uid)
        await repo.set_xp(gid, user_id=uid, total_xp=xp)

    rows, total = await repo.leaderboard(gid, limit=2, offset=2)
    assert total == 4
    assert [r.user_id for r in rows] == [3, 1]


@pytest.mark.asyncio
async def test_rank_of_user(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = UserXpRepository(db_session)

    for uid, xp in [(1, 100), (2, 500), (3, 200), (4, 800)]:
        await repo.get_or_create(gid, user_id=uid)
        await repo.set_xp(gid, user_id=uid, total_xp=xp)

    assert await repo.rank_of(gid, user_id=4) == 1
    assert await repo.rank_of(gid, user_id=1) == 4
    assert await repo.rank_of(gid, user_id=999) is None
