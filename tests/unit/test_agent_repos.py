import uuid

import pytest

from app.models.guild import Guild
from app.repositories.agent_message import AgentMessageRepository


async def _guild(session):
    gid = uuid.uuid4()
    session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    await session.commit()
    return gid


@pytest.mark.asyncio
async def test_add_and_recent_turns_ordered(db_session):
    gid = await _guild(db_session)
    repo = AgentMessageRepository(db_session)
    cid = uuid.uuid4()
    await repo.add_turn(gid, cid, "user", "u1")
    await repo.add_turn(gid, cid, "assistant", "a1", discord_message_id=111)
    await repo.add_turn(gid, cid, "user", "u2")
    await db_session.commit()
    turns = await repo.recent_turns(cid, limit=10, char_cap=10_000)
    assert [t["role"] for t in turns] == ["user", "assistant", "user"]
    assert turns[0]["content"] == "u1"


@pytest.mark.asyncio
async def test_recent_turns_limit_keeps_latest(db_session):
    gid = await _guild(db_session)
    repo = AgentMessageRepository(db_session)
    cid = uuid.uuid4()
    for i in range(5):
        await repo.add_turn(gid, cid, "user", f"m{i}")
    await db_session.commit()
    turns = await repo.recent_turns(cid, limit=2, char_cap=10_000)
    assert [t["content"] for t in turns] == ["m3", "m4"]


@pytest.mark.asyncio
async def test_conversation_of(db_session):
    gid = await _guild(db_session)
    repo = AgentMessageRepository(db_session)
    cid = uuid.uuid4()
    await repo.add_turn(gid, cid, "assistant", "a", discord_message_id=999)
    await db_session.commit()
    assert await repo.conversation_of(999) == cid
    assert await repo.conversation_of(123) is None
