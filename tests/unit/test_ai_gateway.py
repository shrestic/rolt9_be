import uuid
from datetime import UTC, datetime

import pytest

from app.models.guild import Guild
from app.models.guild_ai_config import GuildAIConfig
from app.repositories.ai_config import AIConfigRepository
from app.repositories.ai_usage import AIUsageRepository
from app.repositories.guild import GuildRepository
from app.services.ai.ai_gateway import AIGateway, month_key
from app.services.ai.provider import FakeAIProvider

GID = 2024
NOW = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)


def test_month_key():
    assert month_key(NOW) == "2026-05"


async def _setup(db_session, *, enabled=True, budget=100_000, provider=None):
    gid = uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=GID, name="g", icon_url=None, is_active=True))
    db_session.add(GuildAIConfig(guild_id=gid, enabled=enabled, monthly_token_budget=budget))
    await db_session.commit()
    gw = AIGateway(
        guild_repo=GuildRepository(db_session),
        config_repo=AIConfigRepository(db_session),
        usage_repo=AIUsageRepository(db_session),
        provider=provider or FakeAIProvider(text="hi", input_tokens=5, output_tokens=7),
    )
    return gid, gw


@pytest.mark.asyncio
async def test_complete_happy_records_tokens(db_session):
    gid, gw = await _setup(db_session)
    text = await gw.complete(guild_discord_id=GID, system="s", prompt="p", now=NOW)
    assert text == "hi"
    assert await AIUsageRepository(db_session).tokens_this_period(gid, "2026-05") == 12


@pytest.mark.asyncio
async def test_disabled_raises(db_session):
    _, gw = await _setup(db_session, enabled=False)
    with pytest.raises(ValueError):
        await gw.complete(guild_discord_id=GID, system="s", prompt="p", now=NOW)


@pytest.mark.asyncio
async def test_unconfigured_provider_raises(db_session):
    class _NoKey(FakeAIProvider):
        available = False

    _, gw = await _setup(db_session, provider=_NoKey())
    with pytest.raises(ValueError):
        await gw.complete(guild_discord_id=GID, system="s", prompt="p", now=NOW)


@pytest.mark.asyncio
async def test_over_budget_raises(db_session):
    gid, gw = await _setup(db_session, budget=10)
    await AIUsageRepository(db_session).add_tokens(gid, "2026-05", 10)
    await db_session.commit()
    with pytest.raises(ValueError):
        await gw.complete(guild_discord_id=GID, system="s", prompt="p", now=NOW)
