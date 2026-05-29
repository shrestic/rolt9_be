import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest

from app.models.guild import Guild
from app.models.guild_leveling_config import GuildLevelingConfig
from app.repositories.user_xp import UserXpRepository
from app.services.leveling.xp_decay import XpDecaySweeper, sweep_inactive_xp


async def _seed(session, gid, *, percent=10, days=7):
    session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    session.add(
        GuildLevelingConfig(
            guild_id=gid,
            enabled=True,
            xp_decay_enabled=True,
            xp_decay_percent=percent,
            xp_decay_inactivity_days=days,
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_decay_page_applies_compounded_decay(db_session):
    gid = uuid.uuid4()
    await _seed(db_session, gid, percent=10, days=7)
    repo = UserXpRepository(db_session)
    now = datetime(2026, 5, 29, tzinfo=UTC)
    await repo.set_xp(gid, user_id=1, total_xp=1000, last_xp_at=now - timedelta(days=20))

    sweeper = XpDecaySweeper(db_session, repo)
    page = await sweeper.decay_page(now=now, after_id=None, limit=100)

    assert page.scanned == 1
    assert page.decayed == 1
    row = await repo.get(gid, user_id=1)
    assert row.total_xp == 810
    assert row.last_decay_at is not None


@pytest.mark.asyncio
async def test_decay_page_skips_not_yet_inactive(db_session):
    gid = uuid.uuid4()
    await _seed(db_session, gid, percent=10, days=7)
    repo = UserXpRepository(db_session)
    now = datetime(2026, 5, 29, tzinfo=UTC)
    await repo.set_xp(gid, user_id=1, total_xp=1000, last_xp_at=now - timedelta(days=3))

    sweeper = XpDecaySweeper(db_session, repo)
    page = await sweeper.decay_page(now=now, after_id=None, limit=100)

    assert page.scanned == 1
    assert page.decayed == 0
    row = await repo.get(gid, user_id=1)
    assert row.total_xp == 1000
    assert row.last_decay_at is None


@pytest.mark.asyncio
async def test_decay_page_floors_at_level_threshold(db_session):
    gid = uuid.uuid4()
    await _seed(db_session, gid, percent=10, days=7)
    repo = UserXpRepository(db_session)
    now = datetime(2026, 5, 29, tzinfo=UTC)
    await repo.set_xp(gid, user_id=1, total_xp=1000, last_xp_at=now - timedelta(days=28))

    sweeper = XpDecaySweeper(db_session, repo)
    await sweeper.decay_page(now=now, after_id=None, limit=100)

    row = await repo.get(gid, user_id=1)
    assert row.total_xp == 770


@pytest.mark.asyncio
async def test_sweep_inactive_xp_drains_all_pages(db_session):
    gid = uuid.uuid4()
    await _seed(db_session, gid, percent=10, days=7)
    repo = UserXpRepository(db_session)
    now = datetime(2026, 5, 29, tzinfo=UTC)
    for uid in (1, 2, 3):
        await repo.set_xp(gid, user_id=uid, total_xp=1000, last_xp_at=now - timedelta(days=20))

    @asynccontextmanager
    async def fake_scope():
        yield db_session

    total = await sweep_inactive_xp(now=now, batch_size=2, scope=fake_scope)
    assert total == 3
    for uid in (1, 2, 3):
        row = await repo.get(gid, user_id=uid)
        assert row.total_xp == 810
