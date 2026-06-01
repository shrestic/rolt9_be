"""Reminder cog — quét DB mỗi phút, tới giờ thì gửi lời nhắc + @ping đúng người.

Loop mỏng; logic gửi ở `_fire_due` (test được). Đánh dấu `fired` sau khi cố gửi (kể cả
lỗi/kênh mất) để KHÔNG lặp lại mỗi phút. Reminder nằm trong DB nên restart vẫn còn nguyên.
"""

import logging
from datetime import UTC, datetime

import discord
from discord.ext import commands, tasks

from app.db.session import session_scope
from app.discord_io.client import DiscordClient
from app.discord_io.errors import DiscordError
from app.repositories.reminder import ReminderRepository

log = logging.getLogger(__name__)

CHECK_SECONDS = 60  # quét mỗi phút — đủ mịn cho báo thức, nhẹ tải


class ReminderCog(commands.Cog):
    def __init__(self, bot: commands.Bot, discord_io: DiscordClient):
        self.bot = bot
        self.discord_io = discord_io

    async def cog_load(self) -> None:
        self.reminder_tick.start()

    def cog_unload(self) -> None:
        self.reminder_tick.cancel()

    @tasks.loop(seconds=CHECK_SECONDS)
    async def reminder_tick(self) -> None:
        try:
            await self._fire_due(datetime.now(UTC))
        except Exception:  # noqa: BLE001 — lỗi 1 nhịp không được làm chết loop
            log.exception("reminder: tick failed")

    @reminder_tick.before_loop
    async def _before(self) -> None:
        await self.bot.wait_until_ready()

    async def _fire_due(self, now: datetime) -> None:
        """Lấy các lời nhắc tới giờ, gửi từng cái, rồi đánh dấu đã bắn."""
        async with session_scope() as session:
            repo = ReminderRepository(session)
            for r in await repo.due(now):
                await self._send(r)
                await repo.mark_fired(r.id)  # luôn mark để không lặp lại

    async def _send(self, reminder) -> None:
        channel = self.bot.get_channel(reminder.channel_id)
        if channel is None:
            log.warning("reminder %s: không thấy kênh %s", reminder.id, reminder.channel_id)
            return
        mentions = " ".join(f"<@{uid}>" for uid in (reminder.target_ids or []))
        text = f"⏰ {mentions} Tới giờ rồi nè: {reminder.message}".strip()
        try:
            await channel.send(text[:2000])
        except (DiscordError, discord.DiscordException):
            log.warning("reminder %s: gửi thất bại", reminder.id)
