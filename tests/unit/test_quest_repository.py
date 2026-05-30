import uuid

import pytest

from app.models.guild import Guild
from app.repositories.quest import QuestRepository


async def _seed_guild(session, gid):
    session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    await session.commit()


def _data(**over):
    base = {
        "name": "Earn 500",
        "description": "Earn 500 coins today",
        "period": "daily",
        "objective_type": "earn_coins",
        "target": 500,
        "reward_coins": 100,
        "enabled": True,
    }
    base.update(over)
    return base


@pytest.mark.asyncio
async def test_create_and_list(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = QuestRepository(db_session)
    q = await repo.create(gid, _data())
    assert q.id is not None
    rows = await repo.list_for_guild(gid)
    assert [r.name for r in rows] == ["Earn 500"]


@pytest.mark.asyncio
async def test_list_enabled_filters(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = QuestRepository(db_session)
    await repo.create(gid, _data(name="A", objective_type="earn_coins", enabled=True))
    await repo.create(gid, _data(name="B", objective_type="daily_claim", enabled=True))
    await repo.create(gid, _data(name="C", objective_type="earn_coins", enabled=False))
    earn = await repo.list_enabled(gid, objective_type="earn_coins")
    assert {r.name for r in earn} == {"A"}
    all_enabled = await repo.list_enabled(gid)
    assert {r.name for r in all_enabled} == {"A", "B"}


@pytest.mark.asyncio
async def test_update_and_delete(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = QuestRepository(db_session)
    q = await repo.create(gid, _data())
    updated = await repo.update(q, {"target": 999, "enabled": False})
    assert updated.target == 999
    assert updated.enabled is False
    assert await repo.get(gid, q.id) is not None
    await repo.delete(q)
    assert await repo.get(gid, q.id) is None
