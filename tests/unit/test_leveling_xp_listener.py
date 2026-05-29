from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.cache.leveling_config_cache import CachedLevelingConfig
from app.bot.listeners.xp_listener import handle_message


def _msg(*, content="hello there", bot=False, in_guild=True, channel_id=1, user_id=42):
    author = SimpleNamespace(id=user_id, bot=bot, display_name="alice", roles=[])
    guild = SimpleNamespace(id=10) if in_guild else None
    channel = SimpleNamespace(id=channel_id)
    return SimpleNamespace(content=content, author=author, guild=guild, channel=channel)


@pytest.mark.asyncio
async def test_skips_bot_authors():
    cache = AsyncMock()
    service = AsyncMock()
    await handle_message(_msg(bot=True), cache=cache, service_factory=lambda: service)
    cache.get.assert_not_called()
    service.process_message.assert_not_called()


@pytest.mark.asyncio
async def test_skips_dms():
    cache = AsyncMock()
    service = AsyncMock()
    await handle_message(_msg(in_guild=False), cache=cache, service_factory=lambda: service)
    cache.get.assert_not_called()


@pytest.mark.asyncio
async def test_skips_when_cache_returns_none():
    cache = AsyncMock()
    cache.get.return_value = None
    service = AsyncMock()
    await handle_message(_msg(), cache=cache, service_factory=lambda: service)
    service.process_message.assert_not_called()


@pytest.mark.asyncio
async def test_calls_service_with_message_fields():
    cache = AsyncMock()
    cache.get.return_value = CachedLevelingConfig(
        enabled=True,
        xp_min=15,
        xp_max=25,
        cooldown_seconds=60,
        min_message_length=4,
        ignore_emoji_only=True,
        ignore_link_only=True,
        ignored_channel_ids=[],
        ignored_role_ids=[],
        notification_mode="off",
        notification_channel_id=None,
        level_role_mode="replacing",
    )
    service = AsyncMock()
    service.process_message.return_value = None
    await handle_message(_msg(), cache=cache, service_factory=lambda: service)
    service.process_message.assert_awaited_once()
    kwargs = service.process_message.await_args.kwargs
    assert kwargs["guild_discord_id"] == 10
    assert kwargs["user_id"] == 42
    assert kwargs["username"] == "alice"
    assert kwargs["content"] == "hello there"
    assert kwargs["channel_id"] == 1
