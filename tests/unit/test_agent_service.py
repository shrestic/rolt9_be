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
    s = build_system("You are a robot cat.", "- name Phong", "Phong")
    assert "robot cat" in s
    assert "Phong" in s
    assert "tool" in s.lower()  # nudge to use a tool


def test_build_system_includes_memory_doc_and_channel_context():
    s = build_system(
        "You are a robot cat.",
        "",
        "Phong",
        memory_doc="- call An a jerk",
        channel_context="An: hello\nPhong: hi",
    )
    assert "jerk" in s
    assert "SERVER MEMORY" in s
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
            persona="You are a fun assistant.",
        )
    )
    await db_session.commit()
    gateway = AIGateway(
        guild_repo=GuildRepository(db_session),
        config_repo=AIConfigRepository(db_session),
        usage_repo=AIUsageRepository(db_session),
        provider=provider or FakeAIProvider(text="hi", cost_usd=0.0),
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
    assert text == "hi"
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
    # correct channel -> replies
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
    # Seed an old assistant turn with discord_message_id=555 belonging to the old conversation.
    cid = uuid.uuid4()
    await AgentMessageRepository(db_session).add_turn(
        gid, cid, "assistant", "old line", discord_message_id=555
    )
    await db_session.commit()
    result = await svc.respond(
        guild_discord_id=GID,
        channel_id=10,
        user_discord_id=1,
        user_name="P",
        message_text="continue",
        reference_message_id=555,
    )
    assert result is not None
    assert result[0] == cid  # continues the correct old conversation


@pytest.mark.asyncio
async def test_respond_continues_recent_conversation_without_reference(db_session):
    # No reply, but just spoke in the same (channel, user) -> continue the recent conversation.
    gid, svc = await _svc(db_session)
    cid = uuid.uuid4()
    await AgentMessageRepository(db_session).add_turn(
        gid, cid, "assistant", "previous line", channel_id=10, user_discord_id=1
    )
    await db_session.commit()
    result = await svc.respond(
        guild_discord_id=GID,
        channel_id=10,
        user_discord_id=1,
        user_name="P",
        message_text="continue",
        reference_message_id=None,
    )
    assert result is not None
    assert result[0] == cid  # continues the recent conversation even without a reply


@pytest.mark.asyncio
async def test_followup_without_reply_continues_same_conversation_end_to_end(db_session):
    # Go the WHOLE real path: respond #1 -> remember (persist) -> respond #2 WITHOUT a reply.
    # Turn 2 must continue turn 1's conversation thanks to the window (channel+user match), not create a new one.
    gid, svc = await _svc(db_session)
    first = await svc.respond(
        guild_discord_id=GID,
        channel_id=10,
        user_discord_id=1,
        user_name="P",
        message_text="hi bot",
        reference_message_id=None,
    )
    assert first is not None
    cid1 = first[0]
    await svc.remember(
        guild_discord_id=GID,
        conversation_id=cid1,
        user_discord_id=1,
        user_text="hi bot",
        assistant_text="hi",
        bot_message_id=1001,
        channel_id=10,
    )
    await db_session.commit()

    second = await svc.respond(
        guild_discord_id=GID,
        channel_id=10,
        user_discord_id=1,
        user_name="P",
        message_text="keep going",
        reference_message_id=None,  # NO reply
    )
    assert second is not None
    assert second[0] == cid1  # auto-continues the old conversation, doesn't open a new one

    # Someone else in the same channel -> must NOT be wrongly joined to P's conversation.
    other = await svc.respond(
        guild_discord_id=GID,
        channel_id=10,
        user_discord_id=2,
        user_name="Q",
        message_text="hey bot",
        reference_message_id=None,
    )
    assert other is not None
    assert other[0] != cid1


@pytest.mark.asyncio
async def test_respond_new_conversation_when_prior_is_stale(db_session):
    # Last turn too old (outside the window) -> open a new conversation, don't continue.
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
            content="long ago",
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
        message_text="huh",
        reference_message_id=None,
    )
    assert result is not None
    assert result[0] != cid  # conversation too old -> new conversation


@pytest.mark.asyncio
async def test_remember_persists_and_extracts(db_session):
    gid, svc = await _svc(db_session, provider=FakeAIProvider(text="- name Phong", cost_usd=0.0))
    cid = uuid.uuid4()
    await svc.remember(
        guild_discord_id=GID,
        conversation_id=cid,
        user_discord_id=1,
        user_text="my name is Phong",
        assistant_text="hi Phong",
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
            {"text": "The server has a few people."},
        ],
        cost_usd=0.0,
    )
    _, svc = await _svc(db_session, provider=prov, tools_enabled=True)
    result = await svc.respond(
        guild_discord_id=GID,
        channel_id=10,
        user_discord_id=1,
        user_name="P",
        message_text="how many people",
        reference_message_id=None,
        server_snapshot={"member_count": 5, "roles": [], "channels": []},
    )
    assert result is not None
    assert result[1] == "The server has a few people."


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
    assert result is not None and result[1] == "hi"


@pytest.mark.asyncio
async def test_respond_stages_action_when_enabled(db_session):
    # Model calls toggle_plugin -> stage -> pending has 1 action.
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
            {"text": "Prepared to enable welcome."},
        ],
        cost_usd=0.0,
    )
    _, svc = await _svc(db_session, provider=prov, actions_enabled=True)
    result = await svc.respond(
        guild_discord_id=GID,
        channel_id=10,
        user_discord_id=1,
        user_name="P",
        message_text="enable welcome",
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
        message_text="enable welcome",
        reference_message_id=None,
        commander_perms={},  # no permission -> no action tool -> empty pending
    )
    assert result is not None and result[2] == []


def test_build_system_includes_mention_map():
    # mention_map puts 'name = <@id>' into the prompt so the bot tags for real + remembers with the id
    s = build_system("You are a cat.", "", "Phong", mention_map="Khoi = <@123>")
    assert "<@123>" in s and "Khoi" in s and "tag" in s.lower()


def test_build_system_includes_commander_id_for_self_reference():
    # With user_id -> prompt names '<@id>' of the person chatting + says 'I/me/my' = <@id>, don't make up <@rolt9>.
    s = build_system("You are a cat.", "", "Phong", user_id=705682495592726558)
    assert "<@705682495592726558>" in s
    assert "i/me/my" in s.lower()  # spells it out when they say I/me/my
    assert "rolt9" in s.lower()  # tells it not to use <@rolt9>


# ---------- user-set nicknames -> tag for real (<@id>) ----------

from app.services.ai.agent_service import apply_nick_mentions, extract_nick_mentions  # noqa: E402


def test_extract_nick_mentions_from_memory():
    doc = (
        '- <@945952778998665247> (Jacky Chun) has the nickname "golden chick"\n'
        "- <@661419725091373066> (khoingo76) has the nickname 'jerk Khoi'\n"
        '- line with no id, has "abc" -> skip\n'
        '- <@1> and <@2> on the same line, has "xyz" -> skip (multiple ids)'
    )
    pairs = dict(extract_nick_mentions(doc))
    assert pairs["golden chick"] == 945952778998665247
    assert pairs["jerk Khoi"] == 661419725091373066
    assert "abc" not in pairs  # line with no id
    assert "xyz" not in pairs  # line with multiple ids -> skip to be safe


def test_apply_nick_mentions_tags_plain_and_at_form():
    doc = '- <@945952778998665247> has the nickname "golden chick"'
    # plain text
    out = apply_nick_mentions("hold on, I'll report the gold price for golden chick", doc)
    assert "<@945952778998665247>" in out and "golden chick" not in out
    # the '@golden chick' (fake mention) form also becomes a real mention
    out2 = apply_nick_mentions("Report the gold price for @golden chick", doc)
    assert "<@945952778998665247>" in out2 and "@golden chick" not in out2


def test_apply_nick_mentions_tags_every_occurrence():
    doc = '- <@5> has the nickname "big boss"'
    out = apply_nick_mentions("where's big boss, get big boss in here", doc)
    assert out.count("<@5>") == 2  # tag EVERY mention of the nickname


def test_apply_nick_mentions_noop_without_doc():
    assert apply_nick_mentions("hey golden chick", "") == "hey golden chick"


def test_apply_nick_mentions_tags_multiple_nicknames_of_same_person():
    # One person with MULTIPLE nicknames ('golden chick' and 'golden cream') -> the same sentence must tag BOTH,
    # don't skip the other nickname just because one was already tagged (the guard-by-uid bug is fixed).
    doc = '- <@945> (Jacky) has the nickname "golden chick"\n- <@945> has a new nickname: "golden cream"'
    out = apply_nick_mentions("invite golden chick and golden cream to play", doc)
    assert out == "invite <@945> and <@945> to play"


def test_apply_nick_mentions_longest_nick_wins():
    # Overlapping nicknames -> prefer the LONGER phrase first (match 'golden chick jr' before 'golden chick').
    doc = '- <@1> has the nickname "golden chick"\n- <@2> has the nickname "golden chick jr"'
    out = apply_nick_mentions("call golden chick jr in", doc)
    assert out == "call <@2> in"
