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
from app.repositories.ai_config import AIConfigRepository
from app.repositories.ai_usage import AIUsageRepository
from app.repositories.guild import GuildRepository
from app.repositories.reminder import ReminderRepository
from app.services.ai.ai_gateway import AIGateway
from app.services.ai.provider import get_ai_provider
from app.services.ai.reminder_service import build_reminder_task_system
from app.services.ai.tools.web_search import run_web_search

log = logging.getLogger(__name__)

# Quét mỗi 20s: reminder bắn ở lần quét kế tiếp >= remind_at, nên poll thưa = trễ nhiều.
# 20s -> trễ tối đa ~20s (query `due` có index, 3 lần/phút cực nhẹ). Smart reminder còn +~10-20s
# do web_search + AI, nhưng phần đó không giảm bằng poll được.
CHECK_SECONDS = 20


def _gateway(session) -> AIGateway:
    """Dựng AIGateway từ session (cho smart reminder tra web + AI trả lời lúc tới giờ)."""
    return AIGateway(
        guild_repo=GuildRepository(session),
        config_repo=AIConfigRepository(session),
        usage_repo=AIUsageRepository(session),
        provider=get_ai_provider(),
    )


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
                await self._send(r, session)
                await repo.mark_fired(r.id)  # luôn mark để không lặp lại

    async def _send(self, reminder, session) -> None:
        channel = self.bot.get_channel(reminder.channel_id)
        if channel is None:
            log.warning("reminder %s: không thấy kênh %s", reminder.id, reminder.channel_id)
            return
        mentions = " ".join(f"<@{uid}>" for uid in (reminder.target_ids or []))
        task = getattr(reminder, "task", None)
        if task:
            # SMART reminder: tới giờ TRA SỐNG (web search) + AI trả lời thật theo `task`.
            body = await self._run_task(reminder, channel, session, task)
            if body is None:  # tra/AI hỏng -> vẫn báo đã tới giờ + lý do, không im lặng
                body = f"Tới giờ xem '{task}' rồi mà mình tra không ra lúc này, thử lại sau nha 🥲"
            text = f"⏰ {mentions} {body}".strip()
        else:
            text = f"⏰ {mentions} Tới giờ rồi nè: {reminder.message}".strip()
        try:
            await channel.send(text[:2000])
        except (DiscordError, discord.DiscordException):
            log.warning("reminder %s: gửi thất bại", reminder.id)

    async def _run_task(self, reminder, channel, session, task: str) -> str | None:
        """Tra web về `task` rồi nhờ AI trả lời thật. Lỗi (AI off/thiếu key/tra hỏng) -> None."""
        cfg = await AIConfigRepository(session).get(reminder.guild_id)
        if cfg is None or not cfg.enabled:
            return None
        raw = await run_web_search(task)
        low = raw.lower()
        if "thất bại" in low or "không tìm thấy" in low or "chưa cấu hình" in low:
            return None  # tra web hỏng
        try:
            text = await _gateway(session).complete(
                guild_discord_id=channel.guild.id,
                system=build_reminder_task_system(cfg.persona, task),
                prompt=raw,
            )
        except ValueError:
            return None  # AI off / thiếu key / hết budget
        return text or None
