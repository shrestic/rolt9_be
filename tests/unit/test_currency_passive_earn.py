import types
from unittest.mock import AsyncMock

import pytest

from app.bot.listeners.xp_listener import handle_message


def _message(*, bot=False, guild=True, content="hello world"):
    author = types.SimpleNamespace(id=7, bot=bot, display_name="al", roles=[])
    g = types.SimpleNamespace(id=555) if guild else None
    return types.SimpleNamespace(
        author=author,
        guild=g,
        content=content,
        channel=types.SimpleNamespace(id=1),
    )


class _Cache:
    def __init__(self, enabled=True):
        self._enabled = enabled

    async def get(self, _gid):
        return types.SimpleNamespace(enabled=self._enabled)


@pytest.mark.asyncio
async def test_currency_granted_after_successful_award():
    msg = _message()
    service = AsyncMock()
    service.process_message.return_value = object()  # non-None AwardOutcome
    currency = AsyncMock()
    await handle_message(
        msg,
        cache=_Cache(enabled=True),
        service_factory=lambda: service,
        currency_factory=lambda: currency,
    )
    currency.grant_message_reward.assert_awaited_once_with(guild_discord_id=555, user_id=7)


@pytest.mark.asyncio
async def test_currency_not_granted_when_no_award():
    msg = _message()
    service = AsyncMock()
    service.process_message.return_value = None  # blocked (cooldown / anti-spam)
    currency = AsyncMock()
    await handle_message(
        msg,
        cache=_Cache(enabled=True),
        service_factory=lambda: service,
        currency_factory=lambda: currency,
    )
    currency.grant_message_reward.assert_not_awaited()
