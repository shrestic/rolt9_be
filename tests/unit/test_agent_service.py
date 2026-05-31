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


async def _svc(db_session, provider=None):
    gid = uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=GID, name="g", icon_url=None, is_active=True))
    db_session.add(
        GuildAIConfig(
            guild_id=gid,
            enabled=True,
            agent_enabled=True,
            provider="deepseek",
            model="deepseek-chat",
            api_key_enc=encrypt_str("sk-test"),
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
async def test_reply_returns_text(db_session):
    gid, svc = await _svc(db_session)
    cid = uuid.uuid4()
    text = await svc.reply(
        guild_discord_id=GID,
        user_discord_id=1,
        conversation_id=cid,
        user_name="Phong",
        message_text="hello",
    )
    assert text == "chào"


@pytest.mark.asyncio
async def test_persist_stores_two_turns(db_session):
    gid, svc = await _svc(db_session)
    cid = uuid.uuid4()
    await svc.persist(gid, cid, "hỏi", "đáp", bot_message_id=555)
    await db_session.commit()
    repo = AgentMessageRepository(db_session)
    turns = await repo.recent_turns(cid, limit=10, char_cap=9999)
    assert [t["role"] for t in turns] == ["user", "assistant"]
    assert await repo.conversation_of(555) == cid


@pytest.mark.asyncio
async def test_extract_memory_upserts(db_session):
    gid, svc = await _svc(db_session, provider=FakeAIProvider(text="- tên Phong", cost_usd=0.0))
    await svc.extract_memory(GID, 1, "tôi tên Phong", "chào Phong", "")
    await db_session.commit()
    assert "Phong" in await UserMemoryRepository(db_session).get_facts(gid, 1)
