from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.bot.cogs.xp_decay import XpDecayCog


@pytest.mark.asyncio
async def test_cog_starts_loop_on_init():
    bot = MagicMock()
    cog = XpDecayCog(bot)
    try:
        assert cog.decay_sweep.is_running()
    finally:
        cog.decay_sweep.cancel()


@pytest.mark.asyncio
async def test_loop_body_calls_sweep():
    bot = MagicMock()
    cog = XpDecayCog(bot)
    cog.decay_sweep.cancel()
    with patch(
        "app.bot.cogs.xp_decay.sweep_inactive_xp", new=AsyncMock(return_value=7)
    ) as mock_sweep:
        await cog.decay_sweep.coro(cog)
    mock_sweep.assert_awaited_once()
    kwargs = mock_sweep.await_args.kwargs
    assert isinstance(kwargs["now"], datetime)
    assert kwargs["now"].tzinfo == UTC
