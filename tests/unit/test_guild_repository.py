import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.guild import GuildRepository


@pytest_asyncio.fixture
async def repo(db_session: AsyncSession) -> GuildRepository:
    return GuildRepository(db_session)


@pytest.mark.asyncio
async def test_upsert_creates_guild(repo: GuildRepository):
    g = await repo.upsert(discord_id=42, name="My Server", icon_url=None)
    assert isinstance(g.id, uuid.UUID)
    assert g.is_active is True


@pytest.mark.asyncio
async def test_upsert_reactivates_existing(repo: GuildRepository):
    g1 = await repo.upsert(discord_id=42, name="My Server", icon_url=None)
    await repo.mark_inactive(42)
    g2 = await repo.upsert(discord_id=42, name="My Server v2", icon_url=None)
    assert g2.id == g1.id
    assert g2.is_active is True
    assert g2.name == "My Server v2"


@pytest.mark.asyncio
async def test_get_active_by_discord_ids_filters_active(repo: GuildRepository):
    await repo.upsert(discord_id=1, name="A", icon_url=None)
    await repo.upsert(discord_id=2, name="B", icon_url=None)
    await repo.mark_inactive(2)
    found = await repo.get_active_by_discord_ids([1, 2, 3])
    assert {g.discord_id for g in found} == {1}
