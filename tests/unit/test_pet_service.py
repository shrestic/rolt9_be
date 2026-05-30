import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models.guild import Guild
from app.repositories.guild import GuildRepository
from app.repositories.pet import PetRepository
from app.repositories.pet_cooldown import PetCooldownRepository
from app.repositories.user_wallet import WalletRepository
from app.services.pet import PetService

GID = 1010
NOW = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)


async def _setup(db_session, *, enabled=True, **cfg):
    gid = uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=GID, name="g", icon_url=None, is_active=True))
    await db_session.commit()
    svc = PetService(
        guild_repo=GuildRepository(db_session),
        pet_repo=PetRepository(db_session),
        cooldown_repo=PetCooldownRepository(db_session),
        wallet_repo=WalletRepository(db_session),
    )
    data = {"enabled": enabled}
    data.update(cfg)
    await PetRepository(db_session).upsert_config(gid, data)
    await db_session.commit()
    return gid, svc


@pytest.mark.asyncio
async def test_status_when_disabled(db_session):
    _, svc = await _setup(db_session, enabled=False)
    status = await svc.get_status(guild_discord_id=GID)
    assert status.enabled is False


@pytest.mark.asyncio
async def test_feed_costs_coins_and_raises_status(db_session):
    gid, svc = await _setup(db_session, enabled=True, feed_cost=10, feed_amount=30)
    await WalletRepository(db_session).add_balance(gid, 1, 100)
    await PetRepository(db_session).upsert_config(gid, {"hunger": 50})
    await db_session.commit()
    res = await svc.feed(guild_discord_id=GID, user_id=1, now=NOW)
    assert res.status.hunger == 80
    assert res.balance == 90
    assert res.status.xp == 5


@pytest.mark.asyncio
async def test_feed_insufficient_funds(db_session):
    gid, svc = await _setup(db_session, enabled=True, feed_cost=50)
    await WalletRepository(db_session).add_balance(gid, 1, 10)
    await db_session.commit()
    with pytest.raises(ValueError):
        await svc.feed(guild_discord_id=GID, user_id=1, now=NOW)


@pytest.mark.asyncio
async def test_feed_disabled_raises(db_session):
    _, svc = await _setup(db_session, enabled=False)
    with pytest.raises(ValueError):
        await svc.feed(guild_discord_id=GID, user_id=1, now=NOW)


@pytest.mark.asyncio
async def test_play_increases_happiness_then_cooldown(db_session):
    gid, svc = await _setup(db_session, enabled=True, play_amount=30)
    await PetRepository(db_session).upsert_config(gid, {"happiness": 40})
    await db_session.commit()
    res = await svc.play(guild_discord_id=GID, user_id=1, now=NOW)
    assert res.status.happiness == 70
    with pytest.raises(ValueError):
        await svc.play(guild_discord_id=GID, user_id=1, now=NOW + timedelta(minutes=5))


@pytest.mark.asyncio
async def test_feed_settles_decay_first(db_session):
    gid, svc = await _setup(db_session, enabled=True, feed_cost=0, feed_amount=10, decay_per_day=20)
    await WalletRepository(db_session).add_balance(gid, 1, 0)
    day_ago = NOW - timedelta(days=1)
    await PetRepository(db_session).upsert_config(
        gid, {"hunger": 100, "happiness": 100, "last_decay_at": day_ago}
    )
    await db_session.commit()
    res = await svc.feed(guild_discord_id=GID, user_id=1, now=NOW)
    assert res.status.hunger == 90
    assert res.status.happiness == 80
