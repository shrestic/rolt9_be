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
    await repo.append_note(gid, "call An a jerk")
    await repo.append_note(gid, "An talks without honorifics")
    await repo.append_note(gid, "call An a jerk")  # duplicate -> dropped
    await db_session.commit()
    doc = await repo.get_doc(gid)
    assert doc.count("call An a jerk") == 1
    assert "An talks without honorifics" in doc
    assert doc.startswith("- ")


@pytest.mark.asyncio
async def test_cap_drops_oldest(db_session):
    gid = await _guild(db_session)
    repo = MemoryDocRepository(db_session)
    for i in range(400):
        await repo.append_note(gid, f"fact no {i} " + "x" * 20)
    await db_session.commit()
    doc = await repo.get_doc(gid)
    assert len(doc) <= MEMORY_DOC_CAP
    assert "fact no 399" in doc  # newest kept
    assert "fact no 0 " not in doc  # oldest trimmed


@pytest.mark.asyncio
async def test_set_and_clear(db_session):
    gid = await _guild(db_session)
    repo = MemoryDocRepository(db_session)
    await repo.set_doc(gid, "## Rules\n- no spam")
    await db_session.commit()
    assert "no spam" in await repo.get_doc(gid)
    await repo.clear(gid)
    await db_session.commit()
    assert await repo.get_doc(gid) == ""


@pytest.mark.asyncio
async def test_remove_notes_deletes_matching(db_session):
    gid = await _guild(db_session)
    repo = MemoryDocRepository(db_session)
    await repo.append_note(gid, '<@945> (Jacky) has the nickname "golden chick"')
    await repo.append_note(gid, "thinh.nguyen2's real name is Dat")
    await repo.append_note(gid, "golden chick likes playing Valorant")
    await db_session.commit()

    removed = await repo.remove_notes(
        gid, "golden chick"
    )  # delete 2 lines containing 'golden chick'
    await db_session.commit()
    assert len(removed) == 2
    doc = await repo.get_doc(gid)
    assert "golden chick" not in doc.lower()
    assert "thinh.nguyen2" in doc  # non-matching line -> kept


@pytest.mark.asyncio
async def test_remove_notes_no_match_returns_empty(db_session):
    gid = await _guild(db_session)
    repo = MemoryDocRepository(db_session)
    await repo.append_note(gid, "call An the boss")
    await db_session.commit()
    removed = await repo.remove_notes(gid, "nothing-matches")
    assert removed == []
    assert "call An the boss" in await repo.get_doc(gid)  # doc untouched


@pytest.mark.asyncio
async def test_clear_deletes_row_not_just_empty(db_session):
    from sqlalchemy import func, select

    from app.models.guild_memory_doc import GuildMemoryDoc

    gid = await _guild(db_session)
    repo = MemoryDocRepository(db_session)
    await repo.append_note(gid, "call An the boss")
    await db_session.commit()
    await repo.clear(gid)
    await db_session.commit()
    # FULLY delete the record, don't leave an empty doc row
    cnt = await db_session.scalar(
        select(func.count()).select_from(GuildMemoryDoc).where(GuildMemoryDoc.guild_id == gid)
    )
    assert cnt == 0
    assert await repo.get_doc(gid) == ""


@pytest.mark.asyncio
async def test_remove_all_notes_deletes_row(db_session):
    from sqlalchemy import func, select

    from app.models.guild_memory_doc import GuildMemoryDoc

    gid = await _guild(db_session)
    repo = MemoryDocRepository(db_session)
    await repo.append_note(gid, "nickname golden chick")
    await db_session.commit()
    await repo.remove_notes(
        gid, "golden chick"
    )  # delete the last line -> empty row -> delete the record too
    await db_session.commit()
    cnt = await db_session.scalar(
        select(func.count()).select_from(GuildMemoryDoc).where(GuildMemoryDoc.guild_id == gid)
    )
    assert cnt == 0


@pytest.mark.asyncio
async def test_append_after_clear_recreates(db_session):
    gid = await _guild(db_session)
    repo = MemoryDocRepository(db_session)
    await repo.append_note(gid, "x")
    await repo.clear(gid)
    await repo.append_note(gid, "written again after clearing")  # _row recreates a new row
    await db_session.commit()
    assert "written again after clearing" in await repo.get_doc(gid)
