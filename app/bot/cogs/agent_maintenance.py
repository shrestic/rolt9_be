"""Cog dọn rác agent_message — sweep nền hằng ngày, giữ 90 ngày gần nhất.

Loop mỏng (chỉ lịch + lifecycle); logic ở `purge_old_agent_messages` (test được).
"""

import logging
from datetime import UTC, datetime

from discord.ext import commands, tasks

from app.services.ai.agent_maintenance import purge_old_agent_messages

log = logging.getLogger(__name__)

CLEANUP_HOURS = 24  # quét mỗi ngày — ngưỡng giữ tính theo ngày nên không cần dày hơn


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
        except Exception:  # noqa: BLE001 — 1 lần dọn lỗi không được làm chết loop
            log.exception("agent_message cleanup sweep failed")

    @cleanup_sweep.before_loop
    async def _before(self) -> None:
        # Chờ gateway + DB engine sẵn sàng rồi mới quét.
        await self.bot.wait_until_ready()
