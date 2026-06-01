import uuid
from datetime import date

import pytest

from app.models.guild import Guild
from app.repositories.subscription import SubscriptionRepository


async def _guild(session):
    gid = uuid.uuid4()
    session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    await session.commit()
    return gid


@pytest.mark.asyncio
async def test_create_and_active_queries(db_session):
    gid = await _guild(db_session)
    repo = SubscriptionRepository(db_session)
    await repo.create(
        guild_id=gid, channel_id=1, creator_id=42, topic="chứng khoán", hour=8, minute=0
    )
    await db_session.commit()
    assert len(await repo.active_all()) == 1
    assert len(await repo.active_for_creator(gid, 42)) == 1
    assert await repo.active_for_creator(gid, 99) == []  # người khác -> rỗng


@pytest.mark.asyncio
async def test_mark_ran_and_cancel(db_session):
    gid = await _guild(db_session)
    repo = SubscriptionRepository(db_session)
    s = await repo.create(guild_id=gid, channel_id=1, creator_id=42, topic="vàng", hour=8, minute=0)
    await db_session.commit()

    await repo.mark_ran(s.id, date(2026, 6, 1))
    await db_session.commit()
    assert (await repo.active_for_creator(gid, 42))[0].last_run_on == date(2026, 6, 1)

    assert await repo.cancel(s.id, gid) is True
    await db_session.commit()
    assert await repo.active_for_creator(gid, 42) == []
