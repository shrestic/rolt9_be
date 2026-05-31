import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.core.crypto import encrypt_str
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


async def _setup(
    db_session,
    *,
    enabled=True,
    budget="5",
    provider="anthropic",
    model="claude-haiku-4-5",
    with_key=True,
    ai_provider=None,
):
    gid = uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=GID, name="g", icon_url=None, is_active=True))
    db_session.add(
        GuildAIConfig(
            guild_id=gid,
            enabled=enabled,
            provider=provider,
            model=model,
            api_key_enc=encrypt_str("sk-secret") if with_key else None,
            monthly_budget_usd=Decimal(budget),
        )
    )
    await db_session.commit()
    gw = AIGateway(
        guild_repo=GuildRepository(db_session),
        config_repo=AIConfigRepository(db_session),
        usage_repo=AIUsageRepository(db_session),
        provider=ai_provider
        or FakeAIProvider(text="hi", input_tokens=5, output_tokens=7, cost_usd=0.01),
    )
    return gid, gw


@pytest.mark.asyncio
async def test_complete_happy_records_tokens_and_cost(db_session):
    gid, gw = await _setup(db_session)
    text = await gw.complete(guild_discord_id=GID, system="s", prompt="p", now=NOW)
    assert text == "hi"
    repo = AIUsageRepository(db_session)
    assert await repo.tokens_this_period(gid, "2026-05") == 12
    assert Decimal(await repo.cost_this_period(gid, "2026-05")) == Decimal("0.01")


@pytest.mark.asyncio
async def test_disabled_raises(db_session):
    _, gw = await _setup(db_session, enabled=False)
    with pytest.raises(ValueError):
        await gw.complete(guild_discord_id=GID, system="s", prompt="p", now=NOW)


@pytest.mark.asyncio
async def test_no_key_raises(db_session):
    _, gw = await _setup(db_session, with_key=False)
    with pytest.raises(ValueError):
        await gw.complete(guild_discord_id=GID, system="s", prompt="p", now=NOW)


@pytest.mark.asyncio
async def test_no_provider_or_model_raises(db_session):
    _, gw = await _setup(db_session, provider="", model="")
    with pytest.raises(ValueError):
        await gw.complete(guild_discord_id=GID, system="s", prompt="p", now=NOW)


@pytest.mark.asyncio
async def test_over_usd_budget_raises(db_session):
    gid, gw = await _setup(db_session, budget="0.05")
    await AIUsageRepository(db_session).add_usage(gid, "2026-05", tokens=0, cost_usd=0.05)
    await db_session.commit()
    with pytest.raises(ValueError):
        await gw.complete(guild_discord_id=GID, system="s", prompt="p", now=NOW)
