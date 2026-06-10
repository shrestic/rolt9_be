"""Server Companion cog — periodic tick: the bot observes the server & the AI decides on its own whether to chime in.

Thin loop (schedule + per-guild iteration only); the per-guild logic lives in `_handle_guild` (testable).
Requires the Presence Intent (privileged) to see games — if it's off, the snapshot only has voice + chat.
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
from app.repositories.memory_doc import MemoryDocRepository
from app.services.ai.ai_gateway import AIGateway
from app.services.ai.companion_service import (
    CompanionService,
    build_event_snapshot,
    build_snapshot,
    current_activity_labels,
    newly_started_activities,
)
from app.services.ai.provider import get_ai_provider

log = logging.getLogger(__name__)

TICK_MINUTES = 10
HISTORY_LIMIT = 10
# Hard floor between 2 unprompted bot posts (anti-spam) — even when admins set companion_cooldown_min low.
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
        # tasks.loop runs its FIRST iteration right when online (without waiting a full interval) -> on
        # every restart the bot would post immediately even though the cycle isn't due. This flag skips
        # the first tick after each startup.
        self._warmed_up = False
        # (guild_id, user_id) -> set of games ALREADY announced in the current play session. Each game is
        # announced only once; when a game stops it's removed from the set so the next session announces it
        # again. Avoids nagging about the same game being played.
        self._announced_games: dict[tuple[int, int], set[str]] = {}

    async def cog_load(self) -> None:
        self.companion_tick.start()

    def cog_unload(self) -> None:
        self.companion_tick.cancel()

    @tasks.loop(minutes=TICK_MINUTES)
    async def companion_tick(self) -> None:
        # Skip the first tick (runs right when just online) -> don't self-roast on every restart/deploy.
        # Real-time presence (on_presence_update) still works normally if a new game starts.
        if not self._warmed_up:
            self._warmed_up = True
            return
        now = datetime.now(UTC)
        for guild in list(self.bot.guilds):
            try:
                await self._handle_guild(guild, now=now)
            except Exception:  # noqa: BLE001 — one failing guild must not break the rest of the tick
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

    async def _gate(self, session, guild, *, now: datetime):
        """Check the post conditions (enabled + companion_enabled + has a channel + past cooldown).
        Return (guild_row, cfg, channel) if OK, otherwise None."""
        guild_row, cfg = await self._load_cfg(session, int(guild.id))
        if (
            cfg is None
            or not cfg.enabled
            or not cfg.companion_enabled
            or not cfg.companion_channel_id
        ):
            log.info("companion gate: off/no channel (guild %s)", guild.id)
            return None
        # Effective cooldown = max(config, hard floor) -> even if an admin sets it low, no spam.
        # The last-post mark comes from the DB (cfg.companion_last_post_at) so it SURVIVES restart/deploy.
        gap_min = max(cfg.companion_cooldown_min, MIN_GAP_MINUTES)
        last = cfg.companion_last_post_at
        if last is not None:
            elapsed = (now - last).total_seconds()
            if elapsed < gap_min * 60:
                log.info(
                    "companion gate: COOLDOWN %.0fs left (guild %s)",
                    gap_min * 60 - elapsed,
                    guild.id,
                )
                return None
        channel = guild.get_channel(cfg.companion_channel_id)
        if channel is None:
            log.info(
                "companion gate: bot can't see channel %s (guild %s)",
                cfg.companion_channel_id,
                guild.id,
            )
            return None
        return guild_row, cfg, channel

    async def _decide_and_post(self, session, guild, guild_row, cfg, channel, snapshot, *, now):
        """Got a snapshot -> ask the AI (with server memory), post if worth it, set cooldown.
        Shared by both the periodic tick and the real-time presence event."""
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
            log.info("companion: AI chose NOT to speak this time (guild %s)", guild.id)
            return
        try:
            await channel.send(text)
        except (DiscordError, discord.DiscordException):
            log.warning("companion: failed to post in guild %s", guild.id)
            return
        log.info("companion POSTED (guild %s): %s", guild.id, text[:80])
        # Write the post mark to the DB -> cooldown persists across restarts (no more spam after each deploy).
        await AIConfigRepository(session).set_companion_last_post(guild_row.id, now)

    def _strip_self_mention(self, text: str) -> str:
        """Strip any mention OF THE BOT ITSELF from the sentence (the model occasionally tags itself). Return the cleaned string."""
        if not text:
            return text
        bot_id = self.bot.user.id if self.bot.user else None
        if bot_id is not None:
            for token in (f"<@{bot_id}>", f"<@!{bot_id}>"):
                text = text.replace(token, "")
            text = " ".join(text.split())  # collapse extra whitespace left by the strip
        return text.strip()

    async def _handle_guild(self, guild, *, now: datetime) -> None:
        """Periodic tick: snapshot the whole server (games + voice + chat) then let the AI decide."""
        async with session_scope() as session:
            gated = await self._gate(session, guild, now=now)
            if gated is None:
                return
            guild_row, cfg, channel = gated
            recent = [m async for m in channel.history(limit=HISTORY_LIMIT)]
            recent.reverse()  # old -> new
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
        """Real-time: someone JUST started an activity (game/Spotify/stream/watching) -> consider
        roasting NOW, without waiting for the 10' tick. Filter for the exact 'just started' moment
        (skip other presence updates) + still pass the cooldown so no spam."""
        if after is None or getattr(after, "bot", False):
            return
        guild = getattr(after, "guild", None)
        if guild is None:
            return
        # Dedupe per play session: each (person, game) is announced only ONCE. Update the 'announced' set
        # against what's CURRENTLY playing EVEN when this update has no new game (e.g. a game just stopped)
        # -> when a game stops it's forgotten, and the next session announces it again. Avoids nagging when
        # presence flaps / rich-presence changes constantly.
        key = (int(guild.id), int(after.id))
        playing_now = set(current_activity_labels(after))
        announced = self._announced_games.setdefault(key, set())
        announced &= playing_now  # drop stopped games from 'announced'
        activities = newly_started_activities(before, after)
        if not activities:
            if not announced:
                self._announced_games.pop(key, None)  # free memory when no games remain
            return
        fresh = [a for a in activities if a not in announced]
        if not fresh:
            return  # this game was already announced in the current play session
        announced.update(fresh)
        log.info(
            "companion presence: %s just %s (guild %s)",
            getattr(after, "display_name", "?"),
            fresh,
            guild.id,
        )
        now = datetime.now(UTC)
        try:
            await self._handle_presence_event(guild, after, fresh, now=now)
        except Exception:  # noqa: BLE001 — one event's error must not kill the listener
            log.exception(
                "companion: presence event failed for guild %s", getattr(guild, "id", "?")
            )

    async def _handle_presence_event(self, guild, member, activities, *, now: datetime) -> None:
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
