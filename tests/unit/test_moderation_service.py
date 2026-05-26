import pytest

from app.repositories.guild import GuildRepository
from app.repositories.guild_settings import GuildSettingsRepository
from app.repositories.mod_case import ModCaseRepository
from app.services.moderation import Actor, ModerationService
from tests.fakes.discord import FakeDiscordClient

GID = 55


async def _seed_guild(db_session, moderation=None):
    g = await GuildRepository(db_session).upsert(discord_id=GID, name="S", icon_url=None)
    await GuildSettingsRepository(db_session).update_section(g.id, "moderation", moderation or {})
    return g


def _service(db_session, discord_io: FakeDiscordClient) -> ModerationService:
    return ModerationService(
        session=db_session,
        discord_io=discord_io,
        guilds=GuildRepository(db_session),
        settings=GuildSettingsRepository(db_session),
        cases=ModCaseRepository(db_session),
    )


@pytest.mark.asyncio
async def test_ban_writes_case_calls_discord_and_delivers(db_session):
    await _seed_guild(db_session, {"mod_log_channel_id": "123", "dm_on_action": True})
    discord = FakeDiscordClient()
    service = _service(db_session, discord)

    case = await service.ban(
        guild_id=GID,
        target=Actor(user_id=7, username="bad#1"),
        moderator=Actor(user_id=8, username="mod#1"),
        reason="spam",
    )

    assert case.action == "ban" and case.case_number == 1
    assert (GID, 7) in discord.bans
    assert len(discord.posted_messages) == 1
    assert discord.posted_messages[0][0] == 123  # channel_id
    assert len(discord.dms_sent) == 1
    assert discord.dms_sent[0]["action"] == "ban"


@pytest.mark.asyncio
async def test_kick_writes_case(db_session):
    await _seed_guild(db_session)
    discord = FakeDiscordClient()
    case = await _service(db_session, discord).kick(
        guild_id=GID,
        target=Actor(user_id=7, username="x"),
        moderator=Actor(user_id=8, username="m"),
        reason=None,
    )
    assert case.action == "kick"
    assert (GID, 7, None) in discord.kicks


@pytest.mark.asyncio
async def test_mute_sets_timeout_and_duration(db_session):
    await _seed_guild(db_session)
    discord = FakeDiscordClient()
    case = await _service(db_session, discord).mute(
        guild_id=GID,
        target=Actor(user_id=7, username="x"),
        moderator=Actor(user_id=8, username="m"),
        reason="r",
        duration_seconds=120,
    )
    assert case.action == "mute" and case.duration_seconds == 120
    assert len(discord.mutes) == 1
    assert discord.mutes[0][:2] == (GID, 7)


@pytest.mark.asyncio
async def test_unmute_clears_timeout(db_session):
    await _seed_guild(db_session)
    discord = FakeDiscordClient()
    case = await _service(db_session, discord).unmute(
        guild_id=GID,
        target=Actor(user_id=7, username="x"),
        moderator=Actor(user_id=8, username="m"),
        reason=None,
    )
    assert case.action == "unmute"
    assert discord.unmutes == [(GID, 7, None)]


@pytest.mark.asyncio
async def test_unban_calls_revoke(db_session):
    await _seed_guild(db_session)
    discord = FakeDiscordClient()
    discord.bans.add((GID, 7))
    case = await _service(db_session, discord).unban(
        guild_id=GID,
        target=Actor(user_id=7, username="x"),
        moderator=Actor(user_id=8, username="m"),
        reason=None,
    )
    assert case.action == "unban"
    assert (GID, 7) not in discord.bans


@pytest.mark.asyncio
async def test_warn_escalates_on_threshold(db_session):
    await _seed_guild(
        db_session,
        {"warn_escalation": [{"threshold": 2, "action": "mute", "duration_seconds": 60}]},
    )
    discord = FakeDiscordClient()
    service = _service(db_session, discord)
    _, esc1 = await service.warn(
        guild_id=GID,
        target=Actor(user_id=7, username="x"),
        moderator=Actor(user_id=8, username="m"),
        reason="1",
    )
    assert esc1 is None

    _, esc2 = await service.warn(
        guild_id=GID,
        target=Actor(user_id=7, username="x"),
        moderator=Actor(user_id=8, username="m"),
        reason="2",
    )
    assert esc2 is not None and esc2.action == "mute" and esc2.source == "escalation"
    assert len(discord.mutes) == 1  # only the escalation muted


@pytest.mark.asyncio
async def test_deactivate_ban_revokes_discord(db_session):
    g = await _seed_guild(db_session)
    repo = ModCaseRepository(db_session)
    c = await repo.create_case(
        guild_id=g.id,
        action="ban",
        source="manual",
        target_user_id=7,
        target_username="t",
        moderator_user_id=1,
        moderator_username="m",
        reason=None,
    )
    discord = FakeDiscordClient()
    discord.bans.add((GID, 7))
    await _service(db_session, discord).deactivate_case(guild_id=GID, case=c)
    assert (GID, 7) not in discord.bans
    assert c.active is False


@pytest.mark.asyncio
async def test_deactivate_warn_does_not_call_discord(db_session):
    g = await _seed_guild(db_session)
    repo = ModCaseRepository(db_session)
    c = await repo.create_case(
        guild_id=g.id,
        action="warn",
        source="manual",
        target_user_id=7,
        target_username="t",
        moderator_user_id=1,
        moderator_username="m",
        reason=None,
    )
    discord = FakeDiscordClient()
    await _service(db_session, discord).deactivate_case(guild_id=GID, case=c)
    # No revoke call was attempted (would have been a no-op anyway, but verify intent)
    assert discord.bans == set()
    assert c.active is False


# ─────────────────────────────────────────────────────────────────────────
# Edge cases covered by the T1/T2 audit
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_deactivate_mute_unmutes_on_discord(db_session):
    # Deactivating a mute case must also clear the Discord timeout — otherwise
    # the user stays muted on Discord while the dashboard says the case is closed.
    g = await _seed_guild(db_session)
    repo = ModCaseRepository(db_session)
    c = await repo.create_case(
        guild_id=g.id,
        action="mute",
        source="manual",
        target_user_id=7,
        target_username="t",
        moderator_user_id=1,
        moderator_username="m",
        reason=None,
        duration_seconds=3600,
    )
    discord = FakeDiscordClient()
    await _service(db_session, discord).deactivate_case(guild_id=GID, case=c)
    assert len(discord.unmutes) == 1
    assert discord.unmutes[0][:2] == (GID, 7)
    assert c.active is False


@pytest.mark.asyncio
async def test_mute_rejects_duration_over_28_days(db_session):
    # 28 days is Discord's hard cap on timeouts.
    await _seed_guild(db_session)
    discord = FakeDiscordClient()
    too_long = 29 * 86400
    with pytest.raises(ValueError, match="28 days"):
        await _service(db_session, discord).mute(
            guild_id=GID,
            target=Actor(user_id=7, username="x"),
            moderator=Actor(user_id=8, username="m"),
            reason=None,
            duration_seconds=too_long,
        )
    # Nothing should have been written or sent to Discord.
    assert discord.mutes == []


@pytest.mark.asyncio
async def test_warn_escalation_caps_mute_duration_at_28_days(db_session):
    # Admin may configure an escalation rule with a duration > 28 days. The
    # service clamps it so the auto-mute still works instead of raising.
    too_long = 99 * 86400
    await _seed_guild(
        db_session,
        {"warn_escalation": [{"threshold": 1, "action": "mute", "duration_seconds": too_long}]},
    )
    discord = FakeDiscordClient()
    _, esc = await _service(db_session, discord).warn(
        guild_id=GID,
        target=Actor(user_id=7, username="x"),
        moderator=Actor(user_id=8, username="m"),
        reason="r",
    )
    assert esc is not None
    assert esc.duration_seconds == 28 * 86400
    assert len(discord.mutes) == 1


@pytest.mark.asyncio
async def test_unban_raises_when_user_not_banned(db_session):
    # The pre-check prevents the service from recording a misleading "unban"
    # case for a user who was never banned in the first place.
    await _seed_guild(db_session)
    discord = FakeDiscordClient()  # no bans pre-seeded
    with pytest.raises(LookupError, match="not currently banned"):
        await _service(db_session, discord).unban(
            guild_id=GID,
            target=Actor(user_id=7, username="x"),
            moderator=Actor(user_id=8, username="m"),
            reason=None,
        )


@pytest.mark.asyncio
async def test_actions_raise_lookup_error_for_unregistered_guild(db_session):
    # If the bot was just invited and on_guild_join hasn't recorded the row yet,
    # actions should raise LookupError (a DB-layer miss) — not DiscordNotFound,
    # which would falsely imply a Discord-side problem.
    discord = FakeDiscordClient()
    service = _service(db_session, discord)
    with pytest.raises(LookupError, match="not registered"):
        await service.ban(
            guild_id=99999,  # not seeded
            target=Actor(user_id=7, username="x"),
            moderator=Actor(user_id=8, username="m"),
            reason=None,
        )
