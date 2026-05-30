import uuid

import pytest

from app.models.guild import Guild
from app.repositories.minigame_config import MinigameConfigRepository


async def _seed_guild(session, gid):
    session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    await session.commit()


@pytest.mark.asyncio
async def test_get_or_create_defaults(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = MinigameConfigRepository(db_session)
    cfg = await repo.get_or_create(gid)
    assert cfg.enabled is False
    assert cfg.min_bet == 10
    assert cfg.max_bet == 10_000


@pytest.mark.asyncio
async def test_upsert(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = MinigameConfigRepository(db_session)
    cfg = await repo.upsert(gid, {"enabled": True, "min_bet": 50, "max_bet": 5000})
    assert cfg.enabled is True
    assert cfg.min_bet == 50
    assert cfg.max_bet == 5000
