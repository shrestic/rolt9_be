"""Unit tests: xp_listener feeds QuestService on passive coin earn.

We verify that when `grant_message_reward` returns a positive amount,
`quest_factory().record_event` is called with objective_type="earn_coins"
and the exact earned amount — and that when no coins are earned (None/0),
no quest progress is recorded.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.bot.listeners.xp_listener import handle_message


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
async def test_passive_earn_records_quest_progress():
    leveling = MagicMock()
    leveling.process_message = AsyncMock(return_value=SimpleNamespace(old_level=1, new_level=1))
    currency = MagicMock()
    currency.grant_message_reward = AsyncMock(return_value=7)
    quest = MagicMock()
    quest.record_event = AsyncMock()
    await handle_message(
        _message(),
        cache=_Cache(),
        service_factory=lambda: leveling,
        currency_factory=lambda: currency,
        quest_factory=lambda: quest,
    )
    quest.record_event.assert_awaited_once()
    _, kwargs = quest.record_event.call_args
    assert kwargs["objective_type"] == "earn_coins"
    assert kwargs["amount"] == 7


@pytest.mark.asyncio
async def test_no_earn_no_quest_record():
    leveling = MagicMock()
    leveling.process_message = AsyncMock(return_value=None)
    currency = MagicMock()
    currency.grant_message_reward = AsyncMock(return_value=None)
    quest = MagicMock()
    quest.record_event = AsyncMock()
    await handle_message(
        _message(),
        cache=_Cache(),
        service_factory=lambda: leveling,
        currency_factory=lambda: currency,
        quest_factory=lambda: quest,
    )
    quest.record_event.assert_not_awaited()
