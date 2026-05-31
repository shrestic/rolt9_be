import uuid

import pytest

from app.models.guild import Guild
from app.repositories.memory_doc import MEMORY_DOC_CAP, MemoryDocRepository


async def _guild(session):
    gid = uuid.uuid4()
    session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    await session.commit()
    return gid


@pytest.mark.asyncio
async def test_get_default_empty(db_session):
    gid = await _guild(db_session)
    assert await MemoryDocRepository(db_session).get_doc(gid) == ""


@pytest.mark.asyncio
async def test_append_and_dedup(db_session):
    gid = await _guild(db_session)
    repo = MemoryDocRepository(db_session)
    await repo.append_note(gid, "gọi An là thằng loz")
    await repo.append_note(gid, "An nói trống không")
    await repo.append_note(gid, "gọi An là thằng loz")  # trùng -> bỏ
    await db_session.commit()
    doc = await repo.get_doc(gid)
    assert doc.count("gọi An là thằng loz") == 1
    assert "An nói trống không" in doc
    assert doc.startswith("- ")


@pytest.mark.asyncio
async def test_cap_drops_oldest(db_session):
    gid = await _guild(db_session)
    repo = MemoryDocRepository(db_session)
    for i in range(400):
        await repo.append_note(gid, f"fact số {i} " + "x" * 20)
    await db_session.commit()
    doc = await repo.get_doc(gid)
    assert len(doc) <= MEMORY_DOC_CAP
    assert "fact số 399" in doc  # mới nhất còn
    assert "fact số 0 " not in doc  # cũ nhất bị cắt


@pytest.mark.asyncio
async def test_set_and_clear(db_session):
    gid = await _guild(db_session)
    repo = MemoryDocRepository(db_session)
    await repo.set_doc(gid, "## Luật\n- không spam")
    await db_session.commit()
    assert "không spam" in await repo.get_doc(gid)
    await repo.clear(gid)
    await db_session.commit()
    assert await repo.get_doc(gid) == ""
