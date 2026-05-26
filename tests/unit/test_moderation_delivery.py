from types import SimpleNamespace

import pytest

from app.discord_io.errors import DiscordError
from app.services.moderation.delivery import deliver_case
from tests.fakes.discord import FakeDiscordClient


def _case(**kw):
    defaults = {
        "case_number": 1,
        "action": "ban",
        "source": "manual",
        "target_user_id": 7,
        "target_username": "bad#1",
        "moderator_user_id": 8,
        "moderator_username": "mod#1",
        "reason": "spam",
        "duration_seconds": None,
    }
    defaults.update(kw)
    return SimpleNamespace(**defaults)


@pytest.mark.asyncio
async def test_posts_embed_to_mod_log_channel():
    discord = FakeDiscordClient()
    await deliver_case(
        discord,
        guild_name="S",
        mod_settings={"mod_log_channel_id": "123"},
        target_user_id=7,
        case=_case(),
    )
    assert len(discord.posted_messages) == 1
    assert discord.posted_messages[0][0] == 123


@pytest.mark.asyncio
async def test_dm_sent_only_when_flag_enabled():
    discord = FakeDiscordClient()
    await deliver_case(
        discord,
        guild_name="S",
        mod_settings={"dm_on_action": True},
        target_user_id=7,
        case=_case(),
    )
    assert len(discord.dms_sent) == 1
    assert discord.dms_sent[0]["user_id"] == 7


@pytest.mark.asyncio
async def test_no_channel_no_dm_when_settings_empty():
    discord = FakeDiscordClient()
    await deliver_case(discord, guild_name="S", mod_settings={}, target_user_id=7, case=_case())
    assert discord.posted_messages == []
    assert discord.dms_sent == []


@pytest.mark.asyncio
async def test_post_failure_is_swallowed():
    discord = FakeDiscordClient(raise_on_post=DiscordError)
    # No exception should propagate
    await deliver_case(
        discord,
        guild_name="S",
        mod_settings={"mod_log_channel_id": "123"},
        target_user_id=7,
        case=_case(),
    )


@pytest.mark.asyncio
async def test_dm_failure_is_swallowed():
    discord = FakeDiscordClient(raise_on_dm=DiscordError)
    await deliver_case(
        discord,
        guild_name="S",
        mod_settings={"dm_on_action": True},
        target_user_id=7,
        case=_case(),
    )
