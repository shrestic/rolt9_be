import uuid

import pytest

from app.models.guild import Guild
from app.repositories.ai_config import AIConfigRepository
from app.repositories.ai_usage import AIUsageRepository


async def _seed_guild(session, gid):
    session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    await session.commit()


@pytest.mark.asyncio
async def test_config_defaults(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = AIConfigRepository(db_session)
    cfg = await repo.get_or_create(gid)
    assert cfg.enabled is False
    assert cfg.monthly_token_budget == 100_000
    updated = await repo.upsert(gid, {"enabled": True, "monthly_token_budget": 5000})
    assert updated.enabled is True
    assert updated.monthly_token_budget == 5000


@pytest.mark.asyncio
async def test_usage_add_and_read(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = AIUsageRepository(db_session)
    assert await repo.tokens_this_period(gid, "2026-05") == 0
    await repo.add_tokens(gid, "2026-05", 30)
    await repo.add_tokens(gid, "2026-05", 12)
    assert await repo.tokens_this_period(gid, "2026-05") == 42
    assert await repo.tokens_this_period(gid, "2026-06") == 0
