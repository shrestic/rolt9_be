import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models.guild import Guild
from app.repositories.reminder import ReminderRepository


async def _guild(session):
    gid = uuid.uuid4()
    session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    await session.commit()
    return gid


async def _mk(repo, gid, *, remind_at, msg="chơi game", task=None):
    return await repo.create(
        guild_id=gid,
        channel_id=123,
        creator_id=999,
        target_ids=[999, 111],
        message=msg,
        remind_at=remind_at,
        task=task,
    )


@pytest.mark.asyncio
async def test_create_stores_task_and_defaults_none(db_session):
    gid = await _guild(db_session)
    repo = ReminderRepository(db_session)
    now = datetime.now(UTC)
    smart = await _mk(repo, gid, remind_at=now + timedelta(hours=1), task="giá vàng hôm nay")
    plain = await _mk(repo, gid, remind_at=now + timedelta(hours=2))
    await db_session.commit()
    assert smart.task == "giá vàng hôm nay"  # smart reminder lưu task
    assert plain.task is None  # reminder thường -> task None


@pytest.mark.asyncio
async def test_due_returns_only_past_unfired(db_session):
    gid = await _guild(db_session)
    repo = ReminderRepository(db_session)
    now = datetime.now(UTC)
    past = await _mk(repo, gid, remind_at=now - timedelta(minutes=1), msg="quá khứ")
    await _mk(repo, gid, remind_at=now + timedelta(hours=1), msg="tương lai")
    await db_session.commit()

    due = await repo.due(now)
    assert [r.id for r in due] == [past.id]  # chỉ cái quá giờ + chưa bắn
    assert due[0].target_ids == [999, 111]  # JSON list giữ nguyên


@pytest.mark.asyncio
async def test_mark_fired_excludes_from_due(db_session):
    gid = await _guild(db_session)
    repo = ReminderRepository(db_session)
    now = datetime.now(UTC)
    r = await _mk(repo, gid, remind_at=now - timedelta(minutes=5))
    await db_session.commit()
    await repo.mark_fired(r.id)
    await db_session.commit()
    assert await repo.due(now) == []  # đã bắn -> không lấy lại


@pytest.mark.asyncio
async def test_pending_and_cancel(db_session):
    gid = await _guild(db_session)
    repo = ReminderRepository(db_session)
    now = datetime.now(UTC)
    r = await _mk(repo, gid, remind_at=now + timedelta(days=3))
    await db_session.commit()
    assert len(await repo.pending_for_guild(gid)) == 1
    assert await repo.cancel(r.id, gid) is True
    await db_session.commit()
    assert await repo.pending_for_guild(gid) == []
    assert await repo.cancel(r.id, gid) is False  # huỷ lần 2 -> không còn
