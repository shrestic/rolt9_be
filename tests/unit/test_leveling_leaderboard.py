import uuid

import pytest

from app.models.guild import Guild
from app.repositories.user_xp import UserXpRepository
from app.services.leveling.leaderboard import LeaderboardEntry, LeaderboardService


async def _seed(session):
    gid = uuid.uuid4()
    session.add(Guild(id=gid, discord_id=10, name="g", icon_url=None, is_active=True))
    await session.commit()
    return gid


@pytest.mark.asyncio
async def test_top_returns_ordered_entries(db_session):
    gid = await _seed(db_session)
    repo = UserXpRepository(db_session)
    for uid, xp in [(1, 100), (2, 500), (3, 200)]:
        await repo.get_or_create(gid, user_id=uid)
        await repo.set_xp(gid, user_id=uid, total_xp=xp)

    svc = LeaderboardService(xp_repo=repo)
    page = await svc.top(gid, limit=10, offset=0)
    assert page.total == 3
    assert [e.user_id for e in page.items] == [2, 3, 1]
    assert [e.rank for e in page.items] == [1, 2, 3]
    assert isinstance(page.items[0], LeaderboardEntry)


@pytest.mark.asyncio
async def test_top_paginates(db_session):
    gid = await _seed(db_session)
    repo = UserXpRepository(db_session)
    for uid, xp in [(1, 100), (2, 500), (3, 200), (4, 800)]:
        await repo.get_or_create(gid, user_id=uid)
        await repo.set_xp(gid, user_id=uid, total_xp=xp)

    svc = LeaderboardService(xp_repo=repo)
    page = await svc.top(gid, limit=2, offset=2)
    assert [e.user_id for e in page.items] == [3, 1]
    assert [e.rank for e in page.items] == [3, 4]
