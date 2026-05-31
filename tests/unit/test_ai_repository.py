import uuid
from decimal import Decimal

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
    assert cfg.provider == ""
    assert cfg.model == ""
    assert cfg.api_key_enc is None
    assert Decimal(cfg.monthly_budget_usd) == Decimal("5")
    updated = await repo.upsert(
        gid,
        {
            "enabled": True,
            "provider": "openai",
            "model": "gpt-4o-mini",
            "monthly_budget_usd": Decimal("12.5"),
        },
    )
    assert updated.enabled is True
    assert updated.provider == "openai"
    assert Decimal(updated.monthly_budget_usd) == Decimal("12.5")


@pytest.mark.asyncio
async def test_usage_add_and_read(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = AIUsageRepository(db_session)
    assert await repo.tokens_this_period(gid, "2026-05") == 0
    assert Decimal(await repo.cost_this_period(gid, "2026-05")) == Decimal("0")
    await repo.add_usage(gid, "2026-05", tokens=30, cost_usd=0.01)
    await repo.add_usage(gid, "2026-05", tokens=12, cost_usd=0.02)
    assert await repo.tokens_this_period(gid, "2026-05") == 42
    assert Decimal(await repo.cost_this_period(gid, "2026-05")) == Decimal("0.03")
    assert await repo.tokens_this_period(gid, "2026-06") == 0
    assert Decimal(await repo.cost_this_period(gid, "2026-06")) == Decimal("0")
