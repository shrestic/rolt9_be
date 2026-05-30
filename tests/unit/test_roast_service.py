import uuid

import pytest

from app.models.guild import Guild
from app.models.guild_ai_config import GuildAIConfig
from app.repositories.ai_config import AIConfigRepository
from app.repositories.ai_usage import AIUsageRepository
from app.repositories.guild import GuildRepository
from app.services.ai.ai_gateway import AIGateway
from app.services.ai.provider import FakeAIProvider
from app.services.ai.roast_service import RoastService

GID = 2025


async def _setup(db_session):
    gid = uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=GID, name="g", icon_url=None, is_active=True))
    db_session.add(GuildAIConfig(guild_id=gid, enabled=True, monthly_token_budget=100_000))
    await db_session.commit()
    gw = AIGateway(
        guild_repo=GuildRepository(db_session),
        config_repo=AIConfigRepository(db_session),
        usage_repo=AIUsageRepository(db_session),
        provider=FakeAIProvider(text="Cùn như cái cùi bắp.", input_tokens=5, output_tokens=8),
    )
    return gid, RoastService(gateway=gw)


@pytest.mark.asyncio
async def test_roast_returns_text(db_session):
    _, svc = await _setup(db_session)
    text = await svc.roast(guild_discord_id=GID, target_name="An")
    assert text == "Cùn như cái cùi bắp."


@pytest.mark.asyncio
async def test_roast_propagates_disabled_error(db_session):
    gid = uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=999, name="g", icon_url=None, is_active=True))
    db_session.add(GuildAIConfig(guild_id=gid, enabled=False))
    await db_session.commit()
    gw = AIGateway(
        guild_repo=GuildRepository(db_session),
        config_repo=AIConfigRepository(db_session),
        usage_repo=AIUsageRepository(db_session),
        provider=FakeAIProvider(),
    )
    svc = RoastService(gateway=gw)
    with pytest.raises(ValueError):
        await svc.roast(guild_discord_id=999, target_name="An")
