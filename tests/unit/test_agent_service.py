import uuid
from datetime import UTC

import pytest

from app.core.crypto import encrypt_str
from app.models.guild import Guild
from app.models.guild_ai_config import GuildAIConfig
from app.repositories.agent_message import AgentMessageRepository
from app.repositories.ai_config import AIConfigRepository
from app.repositories.ai_usage import AIUsageRepository
from app.repositories.guild import GuildRepository
from app.repositories.memory_doc import MemoryDocRepository
from app.repositories.reminder import ReminderRepository
from app.repositories.subscription import SubscriptionRepository
from app.repositories.user_memory import UserMemoryRepository
from app.services.ai.agent_service import AgentService, build_system
from app.services.ai.ai_gateway import AIGateway
from app.services.ai.provider import FakeAIProvider

GID = 7777


def test_build_system_includes_persona_and_facts():
    s = build_system("Bạn là mèo máy.", "- tên Phong", "Phong")
    assert "mèo máy" in s
    assert "Phong" in s
    assert "CÔNG CỤ" in s or "công cụ" in s  # nudge dùng tool


def test_build_system_includes_memory_doc_and_channel_context():
    s = build_system(
        "Bạn là mèo máy.",
        "",
        "Phong",
        memory_doc="- gọi An là thằng loz",
        channel_context="An: hello\nPhong: hi",
    )
    assert "thằng loz" in s
    assert "TRÍ NHỚ SERVER" in s
    assert "An: hello" in s


async def _svc(
    db_session,
    *,
    provider=None,
    enabled=True,
    agent_enabled=True,
    agent_channel_id=None,
    with_key=True,
    tools_enabled=False,
    actions_enabled=False,
):
    gid = uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=GID, name="g", icon_url=None, is_active=True))
    db_session.add(
        GuildAIConfig(
            guild_id=gid,
            enabled=enabled,
            agent_enabled=agent_enabled,
            agent_channel_id=agent_channel_id,
            tools_enabled=tools_enabled,
            actions_enabled=actions_enabled,
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
        memory_doc_repo=MemoryDocRepository(db_session),
        reminder_repo=ReminderRepository(db_session),
        subscription_repo=SubscriptionRepository(db_session),
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
    conversation_id, text, pending = result
    assert isinstance(conversation_id, uuid.UUID)
    assert text == "chào"
    assert pending == []


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
async def test_respond_continues_recent_conversation_without_reference(db_session):
    # Không reply, nhưng vừa nói trong cùng (kênh, user) -> nối tiếp cuộc gần đây.
    gid, svc = await _svc(db_session)
    cid = uuid.uuid4()
    await AgentMessageRepository(db_session).add_turn(
        gid, cid, "assistant", "câu trước", channel_id=10, user_discord_id=1
    )
    await db_session.commit()
    result = await svc.respond(
        guild_discord_id=GID,
        channel_id=10,
        user_discord_id=1,
        user_name="P",
        message_text="tiếp",
        reference_message_id=None,
    )
    assert result is not None
    assert result[0] == cid  # nối tiếp cuộc gần đây dù không reply


@pytest.mark.asyncio
async def test_followup_without_reply_continues_same_conversation_end_to_end(db_session):
    # Đi HẾT đường thật: respond #1 -> remember (persist) -> respond #2 KHÔNG reply.
    # Lượt 2 phải nối đúng cuộc của lượt 1 nhờ window (kênh+user khớp), không tạo cuộc mới.
    gid, svc = await _svc(db_session)
    first = await svc.respond(
        guild_discord_id=GID,
        channel_id=10,
        user_discord_id=1,
        user_name="P",
        message_text="chào bot",
        reference_message_id=None,
    )
    assert first is not None
    cid1 = first[0]
    await svc.remember(
        guild_discord_id=GID,
        conversation_id=cid1,
        user_discord_id=1,
        user_text="chào bot",
        assistant_text="chào",
        bot_message_id=1001,
        channel_id=10,
    )
    await db_session.commit()

    second = await svc.respond(
        guild_discord_id=GID,
        channel_id=10,
        user_discord_id=1,
        user_name="P",
        message_text="nói tiếp đi",
        reference_message_id=None,  # KHÔNG reply
    )
    assert second is not None
    assert second[0] == cid1  # tự nối cuộc cũ, không mở cuộc mới

    # Người khác trong cùng kênh -> KHÔNG bị nối nhầm vào cuộc của P.
    other = await svc.respond(
        guild_discord_id=GID,
        channel_id=10,
        user_discord_id=2,
        user_name="Q",
        message_text="ê bot",
        reference_message_id=None,
    )
    assert other is not None
    assert other[0] != cid1


@pytest.mark.asyncio
async def test_respond_new_conversation_when_prior_is_stale(db_session):
    # Lượt cuối quá lâu (ngoài window) -> mở cuộc mới, không nối.
    from datetime import datetime, timedelta

    from app.models.agent_message import AgentMessage

    gid, svc = await _svc(db_session)
    cid = uuid.uuid4()
    old = datetime.now(UTC) - timedelta(hours=3)
    db_session.add(
        AgentMessage(
            guild_id=gid,
            conversation_id=cid,
            role="assistant",
            content="lâu rồi",
            channel_id=10,
            user_discord_id=1,
            created_at=old,
        )
    )
    await db_session.commit()
    result = await svc.respond(
        guild_discord_id=GID,
        channel_id=10,
        user_discord_id=1,
        user_name="P",
        message_text="ơ",
        reference_message_id=None,
    )
    assert result is not None
    assert result[0] != cid  # cuộc cũ quá -> cuộc mới


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


@pytest.mark.asyncio
async def test_respond_uses_tools_when_enabled(db_session):
    prov = FakeAIProvider(
        turns=[
            {
                "tool_calls": [
                    {"id": "c1", "name": "server_info", "arguments": '{"kind":"member_count"}'}
                ]
            },
            {"text": "Server có vài người."},
        ],
        cost_usd=0.0,
    )
    _, svc = await _svc(db_session, provider=prov, tools_enabled=True)
    result = await svc.respond(
        guild_discord_id=GID,
        channel_id=10,
        user_discord_id=1,
        user_name="P",
        message_text="bao nhiêu người",
        reference_message_id=None,
        server_snapshot={"member_count": 5, "roles": [], "channels": []},
    )
    assert result is not None
    assert result[1] == "Server có vài người."


@pytest.mark.asyncio
async def test_respond_simple_path_when_tools_off(db_session):
    _, svc = await _svc(db_session, tools_enabled=False)
    result = await svc.respond(
        guild_discord_id=GID,
        channel_id=10,
        user_discord_id=1,
        user_name="P",
        message_text="hi",
        reference_message_id=None,
        server_snapshot=None,
    )
    assert result is not None and result[1] == "chào"


@pytest.mark.asyncio
async def test_respond_stages_action_when_enabled(db_session):
    # Model gọi toggle_plugin -> stage -> pending có 1 action.
    prov = FakeAIProvider(
        turns=[
            {
                "tool_calls": [
                    {
                        "id": "c1",
                        "name": "toggle_plugin",
                        "arguments": '{"plugin":"welcome","enabled":true}',
                    }
                ]
            },
            {"text": "Đã chuẩn bị bật welcome."},
        ],
        cost_usd=0.0,
    )
    _, svc = await _svc(db_session, provider=prov, actions_enabled=True)
    result = await svc.respond(
        guild_discord_id=GID,
        channel_id=10,
        user_discord_id=1,
        user_name="P",
        message_text="bật welcome",
        reference_message_id=None,
        commander_perms={"manage_guild": True},
    )
    assert result is not None
    _, _, pending = result
    assert len(pending) == 1 and pending[0].kind == "toggle_plugin"


@pytest.mark.asyncio
async def test_respond_no_actions_when_no_perm(db_session):
    _, svc = await _svc(db_session, actions_enabled=True)
    result = await svc.respond(
        guild_discord_id=GID,
        channel_id=10,
        user_discord_id=1,
        user_name="P",
        message_text="bật welcome",
        reference_message_id=None,
        commander_perms={},  # không quyền -> không có action tool -> pending rỗng
    )
    assert result is not None and result[2] == []
