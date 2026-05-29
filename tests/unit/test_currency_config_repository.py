import uuid

import pytest

from app.models.guild import Guild
from app.repositories.currency_config import CurrencyConfigRepository


async def _seed_guild(session, gid):
    session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    await session.commit()


@pytest.mark.asyncio
async def test_get_or_create_defaults(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = CurrencyConfigRepository(db_session)
    cfg = await repo.get_or_create(gid)
    assert cfg.enabled is False
    assert cfg.currency_name == "coins"
    assert cfg.earn_min == 1
    assert cfg.earn_max == 3
    assert cfg.daily_amount == 100
    assert cfg.allow_pay is True


@pytest.mark.asyncio
async def test_upsert_updates_fields(db_session):
    gid = uuid.uuid4()
    await _seed_guild(db_session, gid)
    repo = CurrencyConfigRepository(db_session)
    cfg = await repo.upsert(gid, {"enabled": True, "currency_name": "xu", "daily_amount": 150})
    assert cfg.enabled is True
    assert cfg.currency_name == "xu"
    assert cfg.daily_amount == 150
