import uuid

import pytest

from app.core.crypto import encrypt_str
from app.models.guild import Guild
from app.models.guild_ai_config import GuildAIConfig
from app.repositories.agent_message import AgentMessageRepository
from app.repositories.ai_config import AIConfigRepository
from app.repositories.ai_usage import AIUsageRepository
from app.repositories.guild import GuildRepository
from app.repositories.user_memory import UserMemoryRepository
from app.services.ai.agent_service import AgentService, build_system
from app.services.ai.ai_gateway import AIGateway
from app.services.ai.provider import FakeAIProvider

GID = 7777


def test_build_system_includes_persona_and_facts():
    s = build_system("Bạn là mèo máy.", "- tên Phong", "Phong")
    assert "mèo máy" in s
    assert "Phong" in s


async def _svc(
    db_session,
    *,
    provider=None,
    enabled=True,
    agent_enabled=True,
    agent_channel_id=None,
    with_key=True,
):
    gid = uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=GID, name="g", icon_url=None, is_active=True))
    db_session.add(
        GuildAIConfig(
            guild_id=gid,
            enabled=enabled,
            agent_enabled=agent_enabled,
            agent_channel_id=agent_channel_id,
            provider="deepseek",
            model="deepseek-chat",
            api_key_enc=encrypt_str("sk-test") if with_key else None,
            monthly_budget_usd=5,
            persona="Bạn là trợ lý vui.",
        )
    )
    await db_session.commit()
    gateway = AIGateway(
        guild_repo=GuildRepository(db_session),
        config_repo=AIConfigRepository(db_session),
        usage_repo=AIUsageRepository(db_session),
        provider=provider or FakeAIProvider(text="chào", cost_usd=0.0),
    )
    svc = AgentService(
        guild_repo=GuildRepository(db_session),
        config_repo=AIConfigRepository(db_session),
        agent_msg_repo=AgentMessageRepository(db_session),
        memory_repo=UserMemoryRepository(db_session),
        gateway=gateway,
    )
    return gid, svc


@pytest.mark.asyncio
async def test_respond_returns_conversation_and_text(db_session):
    _, svc = await _svc(db_session)
    result = await svc.respond(
        guild_discord_id=GID,
        channel_id=10,
        user_discord_id=1,
        user_name="Phong",
        message_text="hello",
        reference_message_id=None,
    )
    assert result is not None
    conversation_id, text = result
    assert isinstance(conversation_id, uuid.UUID)
    assert text == "chào"


@pytest.mark.asyncio
async def test_respond_none_when_agent_disabled(db_session):
    _, svc = await _svc(db_session, agent_enabled=False)
    assert (
        await svc.respond(
            guild_discord_id=GID,
            channel_id=10,
            user_discord_id=1,
            user_name="P",
            message_text="hi",
            reference_message_id=None,
        )
        is None
    )


@pytest.mark.asyncio
async def test_respond_none_when_ai_disabled(db_session):
    _, svc = await _svc(db_session, enabled=False)
    assert (
        await svc.respond(
            guild_discord_id=GID,
            channel_id=10,
            user_discord_id=1,
            user_name="P",
            message_text="hi",
            reference_message_id=None,
        )
        is None
    )


@pytest.mark.asyncio
async def test_respond_none_on_wrong_channel(db_session):
    _, svc = await _svc(db_session, agent_channel_id=999)
    assert (
        await svc.respond(
            guild_discord_id=GID,
            channel_id=10,
            user_discord_id=1,
            user_name="P",
            message_text="hi",
            reference_message_id=None,
        )
        is None
    )
    # đúng kênh -> trả lời
    assert (
        await svc.respond(
            guild_discord_id=GID,
            channel_id=999,
            user_discord_id=1,
            user_name="P",
            message_text="hi",
            reference_message_id=None,
        )
        is not None
    )


@pytest.mark.asyncio
async def test_respond_raises_on_missing_key(db_session):
    _, svc = await _svc(db_session, with_key=False)
    with pytest.raises(ValueError):
        await svc.respond(
            guild_discord_id=GID,
            channel_id=10,
            user_discord_id=1,
            user_name="P",
            message_text="hi",
            reference_message_id=None,
        )


@pytest.mark.asyncio
async def test_respond_continues_conversation_via_reference(db_session):
    gid, svc = await _svc(db_session)
    # Seed một lượt assistant cũ với discord_message_id=555 thuộc cuộc cũ.
    cid = uuid.uuid4()
    await AgentMessageRepository(db_session).add_turn(
        gid, cid, "assistant", "câu cũ", discord_message_id=555
    )
    await db_session.commit()
    result = await svc.respond(
        guild_discord_id=GID,
        channel_id=10,
        user_discord_id=1,
        user_name="P",
        message_text="tiếp",
        reference_message_id=555,
    )
    assert result is not None
    assert result[0] == cid  # nối tiếp đúng cuộc cũ


@pytest.mark.asyncio
async def test_remember_persists_and_extracts(db_session):
    gid, svc = await _svc(db_session, provider=FakeAIProvider(text="- tên Phong", cost_usd=0.0))
    cid = uuid.uuid4()
    await svc.remember(
        guild_discord_id=GID,
        conversation_id=cid,
        user_discord_id=1,
        user_text="tôi tên Phong",
        assistant_text="chào Phong",
        bot_message_id=777,
    )
    await db_session.commit()
    msg_repo = AgentMessageRepository(db_session)
    turns = await msg_repo.recent_turns(cid, limit=10, char_cap=9999)
    assert [t["role"] for t in turns] == ["user", "assistant"]
    assert await msg_repo.conversation_of(777) == cid
    assert "Phong" in await UserMemoryRepository(db_session).get_facts(gid, 1)
