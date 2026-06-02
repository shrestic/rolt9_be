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


@pytest.mark.asyncio
async def test_remove_notes_deletes_matching(db_session):
    gid = await _guild(db_session)
    repo = MemoryDocRepository(db_session)
    await repo.append_note(gid, '<@945> (Jacky) có biệt danh "ngọc gà"')
    await repo.append_note(gid, "thinh.nguyen2 tên thật là Đạt")
    await repo.append_note(gid, "ngọc gà thích chơi Valorant")
    await db_session.commit()

    removed = await repo.remove_notes(gid, "ngọc gà")  # xoá 2 dòng chứa 'ngọc gà'
    await db_session.commit()
    assert len(removed) == 2
    doc = await repo.get_doc(gid)
    assert "ngọc gà" not in doc.lower()
    assert "thinh.nguyen2" in doc  # dòng không khớp -> giữ nguyên


@pytest.mark.asyncio
async def test_remove_notes_no_match_returns_empty(db_session):
    gid = await _guild(db_session)
    repo = MemoryDocRepository(db_session)
    await repo.append_note(gid, "gọi An là sếp")
    await db_session.commit()
    removed = await repo.remove_notes(gid, "không-có-gì-khớp")
    assert removed == []
    assert "gọi An là sếp" in await repo.get_doc(gid)  # không đụng doc


@pytest.mark.asyncio
async def test_clear_deletes_row_not_just_empty(db_session):
    from sqlalchemy import func, select

    from app.models.guild_memory_doc import GuildMemoryDoc

    gid = await _guild(db_session)
    repo = MemoryDocRepository(db_session)
    await repo.append_note(gid, "gọi An là sếp")
    await db_session.commit()
    await repo.clear(gid)
    await db_session.commit()
    # XOÁ HẲN record, không để row doc rỗng
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
    await repo.append_note(gid, "biệt danh ngọc gà")
    await db_session.commit()
    await repo.remove_notes(gid, "ngọc gà")  # xoá dòng cuối -> row trống -> xoá luôn record
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
    await repo.append_note(gid, "ghi lại sau khi xoá")  # _row tạo lại row mới
    await db_session.commit()
    assert "ghi lại sau khi xoá" in await repo.get_doc(gid)
