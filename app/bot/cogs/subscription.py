"""Subscription cog — quét mỗi phút, tới giờ thì TRA TIN MỚI (web search) + AI tóm tắt + đăng.

Loop mỏng; logic 'tới giờ chưa' ở `is_due`, prompt ở `build_digest_system` (đều test được).
Mỗi đăng ký đăng 1 lần/ngày (mark_ran theo ngày VN). Web/AI lỗi -> bỏ qua hôm nay, mai thử lại.
"""

import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

from app.db.session import session_scope
from app.discord_io.client import DiscordClient
from app.discord_io.errors import DiscordError
from app.repositories.ai_config import AIConfigRepository
from app.repositories.ai_usage import AIUsageRepository
from app.repositories.guild import GuildRepository
from app.repositories.subscription import SubscriptionRepository
from app.services.ai.ai_gateway import AIGateway
from app.services.ai.provider import get_ai_provider
from app.services.ai.subscription_service import build_digest_system, is_due
from app.services.ai.tools.web_search import run_web_search

log = logging.getLogger(__name__)

CHECK_SECONDS = 60
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def _gateway(session) -> AIGateway:
    return AIGateway(
        guild_repo=GuildRepository(session),
        config_repo=AIConfigRepository(session),
        usage_repo=AIUsageRepository(session),
        provider=get_ai_provider(),
    )


class SubscriptionCog(commands.Cog):
    def __init__(self, bot: commands.Bot, discord_io: DiscordClient):
        self.bot = bot
        self.discord_io = discord_io

    async def cog_load(self) -> None:
        self.subscription_tick.start()

    def cog_unload(self) -> None:
        self.subscription_tick.cancel()

    @tasks.loop(seconds=CHECK_SECONDS)
    async def subscription_tick(self) -> None:
        try:
            await self._fire_due(datetime.now(UTC))
        except Exception:  # noqa: BLE001 — lỗi 1 nhịp không được làm chết loop
            log.exception("subscription: tick failed")

    @subscription_tick.before_loop
    async def _before(self) -> None:
        await self.bot.wait_until_ready()

    async def _fire_due(self, now_utc: datetime) -> None:
        now_vn = now_utc.astimezone(VN_TZ)
        async with session_scope() as session:
            repo = SubscriptionRepository(session)
            for sub in await repo.active_all():
                if not is_due(sub, now_vn):
                    continue
                await self._run(sub, session)
                await repo.mark_ran(sub.id, now_vn.date())  # luôn mark -> mỗi ngày 1 lần

    async def _run(self, sub, session) -> None:
        """Tới giờ: kiểu `message` -> chỉ PING câu nhắc (không web/AI); kiểu `topic` -> tra tin +
        AI tóm tắt rồi đăng. Lỗi -> im lặng (mai thử lại)."""
        channel = self.bot.get_channel(sub.channel_id)
        if channel is None:
            return
        # NHẮC CÁ NHÂN lặp lại: ping thẳng câu đó cho người đăng ký, KHÔNG tra web.
        if getattr(sub, "message", None):
            try:
                await channel.send(f"⏰ <@{sub.creator_id}> {sub.message}"[:2000])
            except (DiscordError, discord.DiscordException):
                log.warning("subscription %s: gửi thất bại", sub.id)
            return
        cfg = await AIConfigRepository(session).get(sub.guild_id)
        if cfg is None or not cfg.enabled:
            return
        raw = await run_web_search(f"{sub.topic} tin tức mới nhất hôm nay")
        low = raw.lower()
        if "thất bại" in low or "không tìm thấy" in low or "chưa cấu hình" in low:
            return  # tra web hỏng -> bỏ qua hôm nay
        try:
            text = await _gateway(session).complete(
                guild_discord_id=channel.guild.id,
                system=build_digest_system(cfg.persona, sub.topic),
                prompt=raw,
            )
        except ValueError:
            return  # AI off / thiếu key / hết budget -> im lặng
        if not text:
            return
        try:
            await channel.send(f"📰 {text}"[:2000])
        except (DiscordError, discord.DiscordException):
            log.warning("subscription %s: gửi thất bại", sub.id)
