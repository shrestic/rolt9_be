import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models.guild import Guild
from app.models.guild_leveling_config import GuildLevelingConfig
from app.repositories.user_xp import UserXpRepository
from app.services.leveling.xp_awarder import AwardOutcome, XpAwarder


async def _seed(session):
    gid = uuid.uuid4()
    session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    cfg = GuildLevelingConfig(guild_id=gid, enabled=True)
    session.add(cfg)
    await session.commit()
    return gid, cfg


@pytest.mark.asyncio
async def test_award_increments_xp(db_session, monkeypatch):
    gid, cfg = await _seed(db_session)
    awarder = XpAwarder(session=db_session, xp_repo=UserXpRepository(db_session))
    monkeypatch.setattr("random.randint", lambda a, b: 20)
    out = await awarder.award(guild_id=gid, user_id=42, config=cfg)
    assert isinstance(out, AwardOutcome)
    assert out.amount == 20
    assert out.old_level == 0
    assert out.new_level == 0  # 20 XP isn't enough for level 1


@pytest.mark.asyncio
async def test_award_respects_cooldown(db_session, monkeypatch):
    gid, cfg = await _seed(db_session)
    awarder = XpAwarder(session=db_session, xp_repo=UserXpRepository(db_session))
    monkeypatch.setattr("random.randint", lambda a, b: 20)

    first = await awarder.award(guild_id=gid, user_id=42, config=cfg)
    assert first is not None
    second = await awarder.award(guild_id=gid, user_id=42, config=cfg)
    assert second is None  # cooldown


@pytest.mark.asyncio
async def test_award_after_cooldown_expires(db_session, monkeypatch):
    gid, cfg = await _seed(db_session)
    cfg.cooldown_seconds = 60
    repo = UserXpRepository(db_session)
    await repo.get_or_create(gid, user_id=42)
    await repo.set_xp(
        gid, user_id=42, total_xp=10, last_xp_at=datetime.now(UTC) - timedelta(seconds=120)
    )

    monkeypatch.setattr("random.randint", lambda a, b: 25)
    awarder = XpAwarder(session=db_session, xp_repo=repo)
    out = await awarder.award(guild_id=gid, user_id=42, config=cfg)
    assert out is not None
    assert out.amount == 25


@pytest.mark.asyncio
async def test_award_triggers_level_up(db_session, monkeypatch):
    gid, cfg = await _seed(db_session)
    repo = UserXpRepository(db_session)
    await repo.get_or_create(gid, user_id=42)
    await repo.set_xp(gid, user_id=42, total_xp=99, last_xp_at=None)
    monkeypatch.setattr("random.randint", lambda a, b: 20)

    awarder = XpAwarder(session=db_session, xp_repo=repo)
    out = await awarder.award(guild_id=gid, user_id=42, config=cfg)
    assert out is not None
    assert out.old_level == 0
    assert out.new_level == 1


@pytest.mark.asyncio
async def test_concurrent_awards_serialize_per_user(db_session, monkeypatch):
    gid, cfg = await _seed(db_session)
    monkeypatch.setattr("random.randint", lambda a, b: 20)
    awarder = XpAwarder(session=db_session, xp_repo=UserXpRepository(db_session))

    results = await asyncio.gather(
        *[awarder.award(guild_id=gid, user_id=42, config=cfg) for _ in range(5)]
    )
    awarded = [r for r in results if r is not None]
    assert len(awarded) == 1
