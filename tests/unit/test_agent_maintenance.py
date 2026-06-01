import contextlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

import app.services.ai.agent_maintenance as maint_mod
from app.models.agent_message import AgentMessage
from app.models.guild import Guild
from app.repositories.agent_message import AgentMessageRepository
from app.services.ai.agent_maintenance import purge_old_agent_messages


async def _guild(session):
    gid = uuid.uuid4()
    session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    await session.commit()
    return gid


async def _add(session, gid, *, content, created_at):
    session.add(
        AgentMessage(
            guild_id=gid,
            conversation_id=uuid.uuid4(),
            role="user",
            content=content,
            created_at=created_at,
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_delete_older_than_drops_only_old(db_session):
    gid = await _guild(db_session)
    now = datetime.now(UTC)
    await _add(db_session, gid, content="cũ", created_at=now - timedelta(days=100))
    await _add(db_session, gid, content="mới", created_at=now - timedelta(days=1))

    deleted = await AgentMessageRepository(db_session).delete_older_than(now - timedelta(days=90))
    await db_session.commit()

    assert deleted == 1
    rows = (await db_session.execute(select(AgentMessage.content))).scalars().all()
    assert list(rows) == ["mới"]  # chỉ giữ cái trong 90 ngày


@pytest.mark.asyncio
async def test_purge_old_agent_messages_default_90_days(db_session, monkeypatch):
    gid = await _guild(db_session)
    now = datetime.now(UTC)
    await _add(db_session, gid, content="cũ", created_at=now - timedelta(days=120))
    await _add(db_session, gid, content="mới", created_at=now - timedelta(days=10))

    @contextlib.asynccontextmanager
    async def fake_scope():
        yield db_session

    monkeypatch.setattr(maint_mod, "session_scope", fake_scope)

    deleted = await purge_old_agent_messages(now=now)  # mặc định giữ 90 ngày
    assert deleted == 1
