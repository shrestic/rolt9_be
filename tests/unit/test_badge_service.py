import uuid

import pytest

from app.models.guild import Guild
from app.models.guild_badge_config import GuildBadgeConfig
from app.repositories.badge_config import BadgeConfigRepository
from app.repositories.guild import GuildRepository
from app.repositories.user_badge import BadgeRepository
from app.repositories.user_wallet import WalletRepository
from app.repositories.user_xp import UserXpRepository
from app.services.badges import BadgeService

GID_DISCORD = 808


async def _setup(db_session, *, enabled=True):
    gid = uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=GID_DISCORD, name="g", icon_url=None, is_active=True))
    db_session.add(GuildBadgeConfig(guild_id=gid, enabled=enabled))
    await db_session.commit()
    svc = BadgeService(
        guild_repo=GuildRepository(db_session),
        badge_repo=BadgeRepository(db_session),
        badge_config_repo=BadgeConfigRepository(db_session),
        xp_repo=UserXpRepository(db_session),
        wallet_repo=WalletRepository(db_session),
    )
    return gid, svc


@pytest.mark.asyncio
async def test_award_new_from_level(db_session):
    gid, svc = await _setup(db_session)
    xp = await UserXpRepository(db_session).get_or_create(gid, 1)
    from app.services.leveling.xp_calculator import total_xp_for_level

    xp.total_xp = total_xp_for_level(10)
    await db_session.commit()
    new = await svc.award_new(guild_discord_id=GID_DISCORD, user_id=1)
    keys = {b.key for b in new}
    assert {"level_5", "level_10"} <= keys
    assert await svc.award_new(guild_discord_id=GID_DISCORD, user_id=1) == []


@pytest.mark.asyncio
async def test_award_new_from_wallet(db_session):
    gid, svc = await _setup(db_session)
    wallet = await WalletRepository(db_session).get_or_create(gid, 1)
    wallet.balance = 10_000
    wallet.longest_streak = 7
    await db_session.commit()
    new = await svc.award_new(guild_discord_id=GID_DISCORD, user_id=1)
    keys = {b.key for b in new}
    assert {"wealth_1k", "wealth_10k", "streak_7"} <= keys


@pytest.mark.asyncio
async def test_award_new_disabled_returns_empty(db_session):
    gid, svc = await _setup(db_session, enabled=False)
    wallet = await WalletRepository(db_session).get_or_create(gid, 1)
    wallet.balance = 100_000
    await db_session.commit()
    assert await svc.award_new(guild_discord_id=GID_DISCORD, user_id=1) == []


@pytest.mark.asyncio
async def test_award_new_unknown_guild_returns_empty(db_session):
    _, svc = await _setup(db_session)
    assert await svc.award_new(guild_discord_id=99999, user_id=1) == []


@pytest.mark.asyncio
async def test_list_for_splits_earned_and_locked(db_session):
    gid, svc = await _setup(db_session)
    await BadgeRepository(db_session).add(gid, 1, "level_5")
    await db_session.commit()
    earned, locked, enabled = await svc.list_for(guild_discord_id=GID_DISCORD, user_id=1)
    assert enabled is True
    assert [b.key for b, _ in earned] == ["level_5"]
    locked_keys = {b.key for b in locked}
    assert "level_5" not in locked_keys
    assert "level_10" in locked_keys
