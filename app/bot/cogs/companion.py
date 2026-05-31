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
from app.services.ai.companion_service import CompanionService, build_snapshot
from app.services.ai.provider import get_ai_provider

log = logging.getLogger(__name__)

TICK_MINUTES = 10
HISTORY_LIMIT = 10


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

    async def _handle_guild(self, guild, *, now: float) -> None:
        async with session_scope() as session:
            guild_row, cfg = await self._load_cfg(session, int(guild.id))
            if (
                cfg is None
                or not cfg.enabled
                or not cfg.companion_enabled
                or not cfg.companion_channel_id
            ):
                return
            last = self.cooldown.get(int(guild.id))
            if last is not None and now - last < cfg.companion_cooldown_min * 60:
                return
            channel = guild.get_channel(cfg.companion_channel_id)
            if channel is None:
                return
            recent = [m async for m in channel.history(limit=HISTORY_LIMIT)]
            recent.reverse()  # cũ -> mới
            bot_id = self.bot.user.id if self.bot.user else None
            snapshot = build_snapshot(
                getattr(guild, "members", []),
                getattr(guild, "voice_channels", []),
                recent,
                bot_id,
            )
            if snapshot is None:
                return
            memory_doc = await MemoryDocRepository(session).get_doc(guild_row.id)
            text = await _build_service(session).decide(
                guild_discord_id=int(guild.id),
                snapshot=snapshot,
                persona=cfg.persona,
                memory_doc=memory_doc,
            )
            if not text:
                return
            try:
                await channel.send(text)
            except (DiscordError, discord.DiscordException):
                log.warning("companion: failed to post in guild %s", guild.id)
                return
            self.cooldown[int(guild.id)] = now
