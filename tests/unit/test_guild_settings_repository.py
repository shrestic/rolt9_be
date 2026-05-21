import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.guild import GuildRepository
from app.repositories.guild_settings import GuildSettingsRepository


@pytest_asyncio.fixture
async def repos(db_session: AsyncSession):
    return GuildRepository(db_session), GuildSettingsRepository(db_session)


@pytest.mark.asyncio
async def test_create_defaults_inserts_empty_dicts(repos):
    guilds, settings = repos
    g = await guilds.upsert(discord_id=1, name="x", icon_url=None)
    s = await settings.create_defaults(g.id)
    assert s.guild_id == g.id
    assert s.moderation == {}
    assert s.welcome == {}


@pytest.mark.asyncio
async def test_create_defaults_idempotent(repos):
    guilds, settings = repos
    g = await guilds.upsert(discord_id=1, name="x", icon_url=None)
    s1 = await settings.create_defaults(g.id)
    s2 = await settings.create_defaults(g.id)
    assert s1.guild_id == s2.guild_id  # second call doesn't error
