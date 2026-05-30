import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models.guild import Guild
from app.repositories.pet import PetRepository
from app.repositories.pet_cooldown import PetCooldownRepository


async def _seed_guild(session, gid):
    session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    await session.commit()


@pytest.mark.asyncio
async def test_get_or_create_defaults(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = PetRepository(db_session)
    pet = await repo.get_or_create(gid)
    assert pet.enabled is False
    assert pet.name == "Pet"
    assert pet.hunger == 100
    assert pet.feed_cost == 10


@pytest.mark.asyncio
async def test_save_state_and_upsert_config(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = PetRepository(db_session)
    pet = await repo.get_or_create(gid)
    now = datetime(2026, 5, 30, tzinfo=UTC)
    await repo.save_state(pet, hunger=80, happiness=70, xp=15, last_decay_at=now)
    again = await repo.get(gid)
    assert (again.hunger, again.happiness, again.xp) == (80, 70, 15)
    cfg = await repo.upsert_config(gid, {"enabled": True, "name": "Rex", "feed_cost": 25})
    assert cfg.enabled is True
    assert cfg.name == "Rex"
    assert cfg.feed_cost == 25


@pytest.mark.asyncio
async def test_try_play_cooldown(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = PetCooldownRepository(db_session)
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    cutoff = now - timedelta(hours=1)
    assert await repo.try_play(gid, 7, now=now, cutoff=cutoff) is True
    assert await repo.try_play(gid, 7, now=now, cutoff=cutoff) is False
    later = now + timedelta(hours=2)
    assert await repo.try_play(gid, 7, now=later, cutoff=later - timedelta(hours=1)) is True
