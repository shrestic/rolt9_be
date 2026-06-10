"""Unit tests for the badge piggyback in handle_message.

Tests verify that on a level-up:
- award_new is called and a badge announcement is posted to the channel
- when there's no level-up, badge logic is entirely skipped
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.bot.listeners.xp_listener import handle_message
from app.services.badges.catalog import by_key


def _message():
    return SimpleNamespace(
        author=SimpleNamespace(id=1, bot=False, display_name="u", roles=[], mention="<@1>"),
        guild=SimpleNamespace(id=100),
        channel=SimpleNamespace(id=200),
        content="hi",
    )


class _Cache:
    async def get(self, _gid):
        return SimpleNamespace(enabled=True)


@pytest.mark.asyncio
async def test_levelup_awards_and_announces_badge():
    leveling = MagicMock()
    leveling.process_message = AsyncMock(return_value=SimpleNamespace(old_level=9, new_level=10))
    badge_svc = MagicMock()
    badge_svc.award_new = AsyncMock(return_value=[by_key("level_10")])
    discord_io = MagicMock()
    discord_io.post_to_channel = AsyncMock()

    await handle_message(
        _message(),
        cache=_Cache(),
        service_factory=lambda: leveling,
        badge_factory=lambda: badge_svc,
        discord_io=discord_io,
    )
    badge_svc.award_new.assert_awaited_once()
    discord_io.post_to_channel.assert_awaited_once()
    call = discord_io.post_to_channel.call_args
    content = call.kwargs.get("content") or (call.args[-1] if call.args else "")
    assert "Veteran" in content


@pytest.mark.asyncio
async def test_no_levelup_no_badge_call():
    leveling = MagicMock()
    leveling.process_message = AsyncMock(return_value=SimpleNamespace(old_level=9, new_level=9))
    badge_svc = MagicMock()
    badge_svc.award_new = AsyncMock(return_value=[])
    discord_io = MagicMock()
    discord_io.post_to_channel = AsyncMock()
    await handle_message(
        _message(),
        cache=_Cache(),
        service_factory=lambda: leveling,
        badge_factory=lambda: badge_svc,
        discord_io=discord_io,
    )
    badge_svc.award_new.assert_not_awaited()
    discord_io.post_to_channel.assert_not_awaited()
