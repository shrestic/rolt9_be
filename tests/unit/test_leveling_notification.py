import uuid

import pytest

from app.models.guild_leveling_config import GuildLevelingConfig
from app.services.leveling.notification import LevelUpNotifier
from tests.fakes.discord import FakeDiscordClient


def _cfg(mode: str, channel_id: int | None = None) -> GuildLevelingConfig:
    return GuildLevelingConfig(
        guild_id=uuid.uuid4(),
        enabled=True,
        notification_mode=mode,
        notification_channel_id=channel_id,
    )


@pytest.mark.asyncio
async def test_channel_mode_posts_to_configured_channel():
    fake = FakeDiscordClient()
    notifier = LevelUpNotifier(discord_io=fake)
    await notifier.send(
        config=_cfg("channel", channel_id=12345),
        user_id=42,
        username="alice",
        new_level=5,
    )
    assert len(fake.posted_messages) == 1
    channel_id, embed, content = fake.posted_messages[0]
    assert channel_id == 12345
    assert content is not None and "alice" in content and "5" in content


@pytest.mark.asyncio
async def test_channel_mode_no_channel_configured_is_noop():
    fake = FakeDiscordClient()
    notifier = LevelUpNotifier(discord_io=fake)
    await notifier.send(
        config=_cfg("channel", channel_id=None),
        user_id=42,
        username="alice",
        new_level=5,
    )
    assert fake.posted_messages == []


@pytest.mark.asyncio
async def test_dm_mode_dms_user():
    fake = FakeDiscordClient()
    notifier = LevelUpNotifier(discord_io=fake)
    await notifier.send(config=_cfg("dm"), user_id=42, username="alice", new_level=5)
    assert len(fake.dms_sent) == 1
    assert fake.dms_sent[0]["user_id"] == 42


@pytest.mark.asyncio
async def test_off_mode_does_nothing():
    fake = FakeDiscordClient()
    notifier = LevelUpNotifier(discord_io=fake)
    await notifier.send(config=_cfg("off"), user_id=42, username="alice", new_level=5)
    assert fake.posted_messages == []
    assert fake.dms_sent == []


@pytest.mark.asyncio
async def test_post_errors_are_swallowed():
    from app.discord_io.errors import DiscordForbidden

    fake = FakeDiscordClient()
    fake.raise_on_post = DiscordForbidden
    notifier = LevelUpNotifier(discord_io=fake)
    # Must NOT raise.
    await notifier.send(
        config=_cfg("channel", channel_id=12345),
        user_id=42,
        username="alice",
        new_level=5,
    )
