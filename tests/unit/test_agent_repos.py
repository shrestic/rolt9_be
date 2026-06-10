import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models.agent_message import AgentMessage
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


@pytest.mark.asyncio
async def test_latest_conversation_continues_recent(db_session):
    # A recent turn for the exact (guild, channel, user) -> return that conversation to continue.
    gid = await _guild(db_session)
    repo = AgentMessageRepository(db_session)
    cid = uuid.uuid4()
    await repo.add_turn(gid, cid, "user", "hi", channel_id=10, user_discord_id=1)
    await db_session.commit()
    found = await repo.latest_conversation(
        gid,
        channel_id=10,
        user_discord_id=1,
        within=timedelta(minutes=20),
        now=datetime.now(UTC),
    )
    assert found == cid


@pytest.mark.asyncio
async def test_latest_conversation_none_when_stale(db_session):
    # Last turn too old (outside the window) -> don't continue, return None (open a new conversation).
    gid = await _guild(db_session)
    repo = AgentMessageRepository(db_session)
    cid = uuid.uuid4()
    old = datetime.now(UTC) - timedelta(hours=2)
    db_session.add(
        AgentMessage(
            guild_id=gid,
            conversation_id=cid,
            role="user",
            content="hi",
            channel_id=10,
            user_discord_id=1,
            created_at=old,
        )
    )
    await db_session.commit()
    found = await repo.latest_conversation(
        gid,
        channel_id=10,
        user_discord_id=1,
        within=timedelta(minutes=20),
        now=datetime.now(UTC),
    )
    assert found is None


@pytest.mark.asyncio
async def test_latest_conversation_scoped_by_channel_and_user(db_session):
    # Same guild but different channel / different person -> must not wrongly continue a conversation.
    gid = await _guild(db_session)
    repo = AgentMessageRepository(db_session)
    cid = uuid.uuid4()
    await repo.add_turn(gid, cid, "user", "hi", channel_id=10, user_discord_id=1)
    await db_session.commit()
    now = datetime.now(UTC)
    within = timedelta(minutes=20)
    assert (
        await repo.latest_conversation(
            gid, channel_id=99, user_discord_id=1, within=within, now=now
        )
        is None
    )
    assert (
        await repo.latest_conversation(
            gid, channel_id=10, user_discord_id=2, within=within, now=now
        )
        is None
    )
