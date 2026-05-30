import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models.guild import Guild
from app.models.guild_karma_config import GuildKarmaConfig
from app.repositories.guild import GuildRepository
from app.repositories.karma import KarmaRepository
from app.repositories.karma_config import KarmaConfigRepository
from app.repositories.karma_grant import KarmaGrantRepository
from app.services.karma import KarmaService

GID = 1111
NOW = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)


async def _setup(db_session, *, enabled=True):
    gid = uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=GID, name="g", icon_url=None, is_active=True))
    db_session.add(GuildKarmaConfig(guild_id=gid, enabled=enabled))
    await db_session.commit()
    svc = KarmaService(
        guild_repo=GuildRepository(db_session),
        karma_repo=KarmaRepository(db_session),
        grant_repo=KarmaGrantRepository(db_session),
        config_repo=KarmaConfigRepository(db_session),
    )
    return gid, svc


@pytest.mark.asyncio
async def test_give_increments_and_ranks(db_session):
    _, svc = await _setup(db_session)
    res = await svc.give(guild_discord_id=GID, giver_id=1, receiver_id=2, now=NOW)
    assert res.receiver_points == 1
    assert res.receiver_rank == 1


@pytest.mark.asyncio
async def test_give_self_rejected(db_session):
    _, svc = await _setup(db_session)
    with pytest.raises(ValueError):
        await svc.give(guild_discord_id=GID, giver_id=1, receiver_id=1, now=NOW)


@pytest.mark.asyncio
async def test_give_disabled_rejected(db_session):
    _, svc = await _setup(db_session, enabled=False)
    with pytest.raises(ValueError):
        await svc.give(guild_discord_id=GID, giver_id=1, receiver_id=2, now=NOW)


@pytest.mark.asyncio
async def test_give_cooldown_same_pair(db_session):
    _, svc = await _setup(db_session)
    await svc.give(guild_discord_id=GID, giver_id=1, receiver_id=2, now=NOW)
    with pytest.raises(ValueError):
        await svc.give(
            guild_discord_id=GID, giver_id=1, receiver_id=2, now=NOW + timedelta(hours=1)
        )
    res = await svc.give(guild_discord_id=GID, giver_id=3, receiver_id=2, now=NOW)
    assert res.receiver_points == 2


@pytest.mark.asyncio
async def test_get_standing(db_session):
    _, svc = await _setup(db_session)
    await svc.give(guild_discord_id=GID, giver_id=1, receiver_id=2, now=NOW)
    standing = await svc.get_standing(guild_discord_id=GID, user_id=2)
    assert standing.points == 1
    assert standing.rank == 1
    none_standing = await svc.get_standing(guild_discord_id=GID, user_id=999)
    assert none_standing.points == 0
    assert none_standing.rank is None
