import uuid

import pytest

from app.models.guild import Guild
from app.repositories.quest import QuestRepository
from app.repositories.quest_progress import QuestProgressRepository


async def _seed(session):
    gid = uuid.uuid4()
    session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    await session.commit()
    quest = await QuestRepository(session).create(
        gid,
        {
            "name": "q",
            "description": None,
            "period": "daily",
            "objective_type": "earn_coins",
            "target": 100,
            "reward_coins": 50,
            "enabled": True,
        },
    )
    return gid, quest


@pytest.mark.asyncio
async def test_increment_accumulates(db_session):
    gid, quest = await _seed(db_session)
    repo = QuestProgressRepository(db_session)
    await repo.increment(quest.id, gid, 7, "2026-05-30", 30)
    await repo.increment(quest.id, gid, 7, "2026-05-30", 40)
    row = await repo.get(quest.id, 7, "2026-05-30")
    assert row.progress == 70


@pytest.mark.asyncio
async def test_increment_separate_periods(db_session):
    gid, quest = await _seed(db_session)
    repo = QuestProgressRepository(db_session)
    await repo.increment(quest.id, gid, 7, "2026-05-30", 30)
    await repo.increment(quest.id, gid, 7, "2026-05-31", 5)
    assert (await repo.get(quest.id, 7, "2026-05-30")).progress == 30
    assert (await repo.get(quest.id, 7, "2026-05-31")).progress == 5


@pytest.mark.asyncio
async def test_try_claim_requires_target_and_is_once(db_session):
    gid, quest = await _seed(db_session)
    repo = QuestProgressRepository(db_session)
    await repo.increment(quest.id, gid, 7, "2026-05-30", 60)
    assert await repo.try_claim(quest.id, 7, "2026-05-30", target=100) is False
    await repo.increment(quest.id, gid, 7, "2026-05-30", 50)  # now 110
    assert await repo.try_claim(quest.id, 7, "2026-05-30", target=100) is True
    assert await repo.try_claim(quest.id, 7, "2026-05-30", target=100) is False


@pytest.mark.asyncio
async def test_list_for_returns_dict_by_quest(db_session):
    gid, quest = await _seed(db_session)
    repo = QuestProgressRepository(db_session)
    await repo.increment(quest.id, gid, 7, "2026-05-30", 30)
    by_quest = await repo.list_for(gid, 7, {"2026-05-30", "2026-W22"})
    assert by_quest[quest.id].progress == 30
