"""Daily background sweep that applies inactivity XP decay.

A thin `discord.ext.tasks` loop: it owns scheduling and lifecycle only, and
delegates all logic to `sweep_inactive_xp`. Kept thin (like `XpListenerCog`)
because the real work lives in a plain, unit-testable async function.
"""

import logging
from datetime import UTC, datetime

from discord.ext import commands, tasks

from app.services.leveling.xp_decay import sweep_inactive_xp

log = logging.getLogger(__name__)

# How often the sweep runs. Day-granularity inactivity thresholds don't need a
# finer cadence; a row that becomes due is picked up on the next daily pass.
DECAY_SWEEP_HOURS = 24


class XpDecayCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.decay_sweep.start()

    def cog_unload(self) -> None:
        self.decay_sweep.cancel()

    @tasks.loop(hours=DECAY_SWEEP_HOURS)
    async def decay_sweep(self) -> None:
        decayed = await sweep_inactive_xp(now=datetime.now(UTC))
        log.info("XP decay sweep complete: %d row(s) decayed.", decayed)

    @decay_sweep.before_loop
    async def _before(self) -> None:
        # Don't sweep until the gateway is connected and the DB engine is live.
        await self.bot.wait_until_ready()
