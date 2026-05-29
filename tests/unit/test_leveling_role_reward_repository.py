import uuid

import pytest

from app.models.guild import Guild
from app.repositories.level_role_reward import LevelRoleRewardRepository


async def _seed(session):
    gid = uuid.uuid4()
    session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    await session.commit()
    return gid


@pytest.mark.asyncio
async def test_list_returns_ordered_by_level(db_session):
    gid = await _seed(db_session)
    repo = LevelRoleRewardRepository(db_session)
    await repo.upsert(gid, level=10, role_id=222)
    await repo.upsert(gid, level=5, role_id=111)
    await repo.upsert(gid, level=20, role_id=333)
    items = await repo.list_by_guild(gid)
    assert [i.level for i in items] == [5, 10, 20]


@pytest.mark.asyncio
async def test_upsert_replaces_role_id(db_session):
    gid = await _seed(db_session)
    repo = LevelRoleRewardRepository(db_session)
    await repo.upsert(gid, level=10, role_id=111)
    await repo.upsert(gid, level=10, role_id=999)
    items = await repo.list_by_guild(gid)
    assert len(items) == 1
    assert items[0].role_id == 999


@pytest.mark.asyncio
async def test_delete_by_level(db_session):
    gid = await _seed(db_session)
    repo = LevelRoleRewardRepository(db_session)
    await repo.upsert(gid, level=10, role_id=111)
    deleted = await repo.delete_by_level(gid, level=10)
    assert deleted is True
    assert await repo.list_by_guild(gid) == []


@pytest.mark.asyncio
async def test_delete_by_role_removes_all_matching(db_session):
    gid = await _seed(db_session)
    repo = LevelRoleRewardRepository(db_session)
    await repo.upsert(gid, level=5, role_id=111)
    await repo.upsert(gid, level=10, role_id=999)
    n = await repo.delete_by_role(gid, role_id=111)
    assert n == 1
    items = await repo.list_by_guild(gid)
    assert [i.role_id for i in items] == [999]
