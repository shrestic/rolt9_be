"""agent_message cleanup cog — daily background sweep, keeps the last 90 days.

Thin loop (schedule + lifecycle only); the logic lives in `purge_old_agent_messages` (testable).
"""

import logging
from datetime import UTC, datetime

from discord.ext import commands, tasks

from app.services.ai.agent_maintenance import purge_old_agent_messages

log = logging.getLogger(__name__)

CLEANUP_HOURS = 24  # sweep daily — the retention threshold is in days so no need to run more often


class AgentMaintenanceCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cleanup_sweep.start()

    def cog_unload(self) -> None:
        self.cleanup_sweep.cancel()

    @tasks.loop(hours=CLEANUP_HOURS)
    async def cleanup_sweep(self) -> None:
        try:
            await purge_old_agent_messages(now=datetime.now(UTC))
        except Exception:  # noqa: BLE001 — one failed sweep must not kill the loop
            log.exception("agent_message cleanup sweep failed")

    @cleanup_sweep.before_loop
    async def _before(self) -> None:
        # Wait for the gateway + DB engine to be ready before sweeping.
        await self.bot.wait_until_ready()
