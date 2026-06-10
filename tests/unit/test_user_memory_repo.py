import uuid

import pytest

from app.models.guild import Guild
from app.repositories.user_memory import UserMemoryRepository


async def _guild(session):
    gid = uuid.uuid4()
    session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    await session.commit()
    return gid


@pytest.mark.asyncio
async def test_get_default_empty(db_session):
    gid = await _guild(db_session)
    repo = UserMemoryRepository(db_session)
    assert await repo.get_facts(gid, 42) == ""


@pytest.mark.asyncio
async def test_upsert_then_get(db_session):
    gid = await _guild(db_session)
    repo = UserMemoryRepository(db_session)
    await repo.upsert_facts(gid, 42, "- likes cats\n- name is Phong")
    await db_session.commit()
    assert "likes cats" in await repo.get_facts(gid, 42)
    await repo.upsert_facts(gid, 42, "- updated")
    await db_session.commit()
    assert await repo.get_facts(gid, 42) == "- updated"


@pytest.mark.asyncio
async def test_clear(db_session):
    gid = await _guild(db_session)
    repo = UserMemoryRepository(db_session)
    await repo.upsert_facts(gid, 42, "x")
    await db_session.commit()
    await repo.clear(gid, 42)
    await db_session.commit()
    assert await repo.get_facts(gid, 42) == ""
