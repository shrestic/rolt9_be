import uuid
from datetime import UTC, datetime

import pytest

from app.models.guild import Guild
from app.repositories.guild import GuildRepository
from app.repositories.quest import QuestRepository
from app.repositories.quest_progress import QuestProgressRepository
from app.repositories.user_wallet import WalletRepository
from app.services.quests import QuestService

GID = 909
NOW = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)


async def _setup(db_session):
    gid = uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=GID, name="g", icon_url=None, is_active=True))
    await db_session.commit()
    svc = QuestService(
        guild_repo=GuildRepository(db_session),
        quest_repo=QuestRepository(db_session),
        progress_repo=QuestProgressRepository(db_session),
        wallet_repo=WalletRepository(db_session),
    )
    return gid, svc


def _qdata(**over):
    base = {
        "name": "Earn 100",
        "description": None,
        "period": "daily",
        "objective_type": "earn_coins",
        "target": 100,
        "reward_coins": 50,
        "enabled": True,
    }
    base.update(over)
    return base


@pytest.mark.asyncio
async def test_record_event_increments_matching_quests(db_session):
    gid, svc = await _setup(db_session)
    qrepo = QuestRepository(db_session)
    await qrepo.create(gid, _qdata(name="earn", objective_type="earn_coins", target=100))
    await qrepo.create(gid, _qdata(name="daily", objective_type="daily_claim", target=5))
    await db_session.commit()
    await svc.record_event(
        guild_discord_id=GID, user_id=1, objective_type="earn_coins", amount=40, now=NOW
    )
    views = await svc.list_quests(guild_discord_id=GID, user_id=1, now=NOW)
    earn = next(v for v in views if v.quest.name == "earn")
    daily = next(v for v in views if v.quest.name == "daily")
    assert earn.progress == 40
    assert daily.progress == 0


@pytest.mark.asyncio
async def test_claim_grants_coins_and_is_once(db_session):
    gid, svc = await _setup(db_session)
    await QuestRepository(db_session).create(gid, _qdata(name="earn", target=100, reward_coins=50))
    await db_session.commit()
    await svc.record_event(
        guild_discord_id=GID, user_id=1, objective_type="earn_coins", amount=100, now=NOW
    )
    result = await svc.claim(guild_discord_id=GID, user_id=1, now=NOW)
    assert result.claimed_count == 1
    assert result.total_coins == 50
    assert "earn" in result.names
    assert (await WalletRepository(db_session).get(gid, 1)).balance == 50
    again = await svc.claim(guild_discord_id=GID, user_id=1, now=NOW)
    assert again.claimed_count == 0


@pytest.mark.asyncio
async def test_claim_skips_incomplete(db_session):
    gid, svc = await _setup(db_session)
    await QuestRepository(db_session).create(gid, _qdata(target=100, reward_coins=50))
    await db_session.commit()
    await svc.record_event(
        guild_discord_id=GID, user_id=1, objective_type="earn_coins", amount=30, now=NOW
    )
    result = await svc.claim(guild_discord_id=GID, user_id=1, now=NOW)
    assert result.claimed_count == 0
    assert result.total_coins == 0


@pytest.mark.asyncio
async def test_list_quests_flags(db_session):
    gid, svc = await _setup(db_session)
    await QuestRepository(db_session).create(gid, _qdata(target=50))
    await db_session.commit()
    await svc.record_event(
        guild_discord_id=GID, user_id=1, objective_type="earn_coins", amount=50, now=NOW
    )
    views = await svc.list_quests(guild_discord_id=GID, user_id=1, now=NOW)
    assert views[0].completed is True
    assert views[0].claimed is False


@pytest.mark.asyncio
async def test_record_event_unknown_guild_silent(db_session):
    _, svc = await _setup(db_session)
    await svc.record_event(
        guild_discord_id=99999, user_id=1, objective_type="earn_coins", amount=10, now=NOW
    )
