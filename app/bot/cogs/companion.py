"""Server Companion cog — tick định kỳ: bot tự quan sát server & AI tự quyết buông câu.

Loop mỏng (chỉ lịch + lặp guild); logic 1 guild ở `_handle_guild` (test được). Cần
Presence Intent (privileged) để thấy game — nếu chưa bật, snapshot chỉ có voice + chat.
"""

import logging
import time

import discord
from discord.ext import commands, tasks

from app.db.session import session_scope
from app.discord_io.client import DiscordClient
from app.discord_io.errors import DiscordError
from app.repositories.ai_config import AIConfigRepository
from app.repositories.ai_usage import AIUsageRepository
from app.repositories.guild import GuildRepository
from app.repositories.memory_doc import MemoryDocRepository
from app.services.ai.ai_gateway import AIGateway
from app.services.ai.companion_service import (
    CompanionService,
    build_event_snapshot,
    build_snapshot,
    newly_started_activities,
)
from app.services.ai.provider import get_ai_provider

log = logging.getLogger(__name__)

TICK_MINUTES = 10
HISTORY_LIMIT = 10
# Sàn cứng giữa 2 lần bot TỰ nói (chống spam) — kể cả khi admin để companion_cooldown_min thấp.
MIN_GAP_MINUTES = 15


def _build_service(session) -> CompanionService:
    gateway = AIGateway(
        guild_repo=GuildRepository(session),
        config_repo=AIConfigRepository(session),
        usage_repo=AIUsageRepository(session),
        provider=get_ai_provider(),
    )
    return CompanionService(gateway=gateway)


class CompanionCog(commands.Cog):
    def __init__(self, bot: commands.Bot, discord_io: DiscordClient):
        self.bot = bot
        self.discord_io = discord_io
        self.cooldown: dict[int, float] = {}

    async def cog_load(self) -> None:
        self.companion_tick.start()

    def cog_unload(self) -> None:
        self.companion_tick.cancel()

    @tasks.loop(minutes=TICK_MINUTES)
    async def companion_tick(self) -> None:
        now = time.monotonic()
        for guild in list(self.bot.guilds):
            try:
                await self._handle_guild(guild, now=now)
            except Exception:  # noqa: BLE001 — 1 guild lỗi không làm hỏng tick còn lại
                log.exception("companion: tick failed for guild %s", getattr(guild, "id", "?"))

    @companion_tick.before_loop
    async def _before(self) -> None:
        await self.bot.wait_until_ready()

    async def _load_cfg(self, session, guild_discord_id: int):
        guild = await GuildRepository(session).get_by_discord_id(guild_discord_id)
        if guild is None:
            return None, None
        cfg = await AIConfigRepository(session).get(guild.id)
        return guild, cfg

    async def _gate(self, session, guild, *, now: float):
        """Kiểm tra đủ điều kiện post (enabled + companion_enabled + có kênh + qua cooldown).
        Trả (guild_row, cfg, channel) nếu OK, ngược lại None."""
        guild_row, cfg = await self._load_cfg(session, int(guild.id))
        if (
            cfg is None
            or not cfg.enabled
            or not cfg.companion_enabled
            or not cfg.companion_channel_id
        ):
            log.info("companion gate: tắt/thiếu kênh (guild %s)", guild.id)
            return None
        # Cooldown hiệu lực = max(cấu hình, sàn cứng) -> dù admin set thấp cũng không spam.
        gap_min = max(cfg.companion_cooldown_min, MIN_GAP_MINUTES)
        last = self.cooldown.get(int(guild.id))
        if last is not None and now - last < gap_min * 60:
            log.info(
                "companion gate: COOLDOWN còn %.0fs (guild %s)",
                gap_min * 60 - (now - last),
                guild.id,
            )
            return None
        channel = guild.get_channel(cfg.companion_channel_id)
        if channel is None:
            log.info(
                "companion gate: bot không thấy kênh %s (guild %s)",
                cfg.companion_channel_id,
                guild.id,
            )
            return None
        return guild_row, cfg, channel

    async def _decide_and_post(self, session, guild, guild_row, cfg, channel, snapshot, *, now):
        """Có snapshot rồi -> hỏi AI (kèm trí nhớ server), post nếu đáng, set cooldown.
        Dùng chung cho cả tick định kỳ lẫn sự kiện presence real-time."""
        if not snapshot:
            return
        memory_doc = await MemoryDocRepository(session).get_doc(guild_row.id)
        text = await _build_service(session).decide(
            guild_discord_id=int(guild.id),
            snapshot=snapshot,
            persona=cfg.persona,
            memory_doc=memory_doc,
        )
        text = self._strip_self_mention(text)
        if not text:
            log.info("companion: AI chọn KHÔNG nói lần này (guild %s)", guild.id)
            return
        try:
            await channel.send(text)
        except (DiscordError, discord.DiscordException):
            log.warning("companion: failed to post in guild %s", guild.id)
            return
        log.info("companion POSTED (guild %s): %s", guild.id, text[:80])
        self.cooldown[int(guild.id)] = now

    def _strip_self_mention(self, text: str) -> str:
        """Gỡ mọi mention TỚI CHÍNH BOT khỏi câu (model lâu lâu tự tag mình). Trả chuỗi đã dọn."""
        if not text:
            return text
        bot_id = self.bot.user.id if self.bot.user else None
        if bot_id is not None:
            for token in (f"<@{bot_id}>", f"<@!{bot_id}>"):
                text = text.replace(token, "")
            text = " ".join(text.split())  # gộp khoảng trắng thừa do vừa gỡ
        return text.strip()

    async def _handle_guild(self, guild, *, now: float) -> None:
        """Tick định kỳ: chụp toàn cảnh server (game + voice + chat) rồi để AI tự quyết."""
        async with session_scope() as session:
            gated = await self._gate(session, guild, now=now)
            if gated is None:
                return
            guild_row, cfg, channel = gated
            recent = [m async for m in channel.history(limit=HISTORY_LIMIT)]
            recent.reverse()  # cũ -> mới
            bot_id = self.bot.user.id if self.bot.user else None
            snapshot = build_snapshot(
                getattr(guild, "members", []),
                getattr(guild, "voice_channels", []),
                recent,
                bot_id,
            )
            await self._decide_and_post(session, guild, guild_row, cfg, channel, snapshot, now=now)

    @commands.Cog.listener()
    async def on_presence_update(self, before, after) -> None:
        """Real-time: ai đó VỪA bắt đầu một hoạt động (game/Spotify/stream/xem) -> cân nhắc
        cà khịa NGAY, không đợi tick 10'. Lọc đúng khoảnh khắc 'vừa bắt đầu' (bỏ qua các
        presence update khác) + vẫn qua cooldown nên không spam."""
        if after is None or getattr(after, "bot", False):
            return
        activities = newly_started_activities(before, after)
        if not activities:
            return
        guild = getattr(after, "guild", None)
        if guild is None:
            return
        log.info(
            "companion presence: %s vừa %s (guild %s)",
            getattr(after, "display_name", "?"),
            activities,
            guild.id,
        )
        now = time.monotonic()
        try:
            await self._handle_presence_event(guild, after, activities, now=now)
        except Exception:  # noqa: BLE001 — lỗi 1 sự kiện không được làm chết listener
            log.exception(
                "companion: presence event failed for guild %s", getattr(guild, "id", "?")
            )

    async def _handle_presence_event(self, guild, member, activities, *, now: float) -> None:
        async with session_scope() as session:
            gated = await self._gate(session, guild, now=now)
            if gated is None:
                return
            guild_row, cfg, channel = gated
            bot_id = self.bot.user.id if self.bot.user else None
            snapshot = build_event_snapshot(
                member,
                activities,
                getattr(guild, "members", []),
                getattr(guild, "voice_channels", []),
                bot_id,
            )
            await self._decide_and_post(session, guild, guild_row, cfg, channel, snapshot, now=now)
