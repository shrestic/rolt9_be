"""Reminder cog — scans the DB every minute; when it's time, sends the reminder + @pings the right people.

Thin loop; the sending logic lives in `_fire_due` (testable). Mark `fired` after attempting to send
(even on error/missing channel) so it does NOT repeat every minute. Reminders live in the DB, so they
survive a restart.
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

# Scan every 20s: a reminder fires on the next scan >= remind_at, so a sparse poll = more delay.
# 20s -> max delay ~20s (the `due` query is indexed, 3x/minute is extremely light). Smart reminders
# add another ~10-20s from web_search + AI, but that part can't be reduced by polling.
CHECK_SECONDS = 20


def _gateway(session) -> AIGateway:
    """Build an AIGateway from a session (for smart reminders to search the web + have AI answer when it's time)."""
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
        except Exception:  # noqa: BLE001 — a single tick error must not kill the loop
            log.exception("reminder: tick failed")

    @reminder_tick.before_loop
    async def _before(self) -> None:
        await self.bot.wait_until_ready()

    async def _fire_due(self, now: datetime) -> None:
        """Fetch the reminders that are due, send each one, then mark them as fired."""
        async with session_scope() as session:
            repo = ReminderRepository(session)
            for r in await repo.due(now):
                await self._send(r, session)
                await repo.mark_fired(r.id)  # always mark so it doesn't repeat

    async def _send(self, reminder, session) -> None:
        channel = self.bot.get_channel(reminder.channel_id)
        if channel is None:
            log.warning("reminder %s: channel %s not found", reminder.id, reminder.channel_id)
            return
        mentions = " ".join(f"<@{uid}>" for uid in (reminder.target_ids or []))
        task = getattr(reminder, "task", None)
        if task:
            # SMART reminder: when it's time, do a LIVE lookup (web search) + have the AI actually answer `task`.
            body = await self._run_task(reminder, channel, session, task)
            if (
                body is None
            ):  # lookup/AI failed -> still announce it's time + a reason, never go silent
                body = f"It's time to check '{task}' but I couldn't dig anything up right now, try again later 🥲"
            text = f"⏰ {mentions} {body}".strip()
        else:
            text = f"⏰ {mentions} It's time: {reminder.message}".strip()
        try:
            await channel.send(text[:2000])
        except (DiscordError, discord.DiscordException):
            log.warning("reminder %s: send failed", reminder.id)

    async def _run_task(self, reminder, channel, session, task: str) -> str | None:
        """Search the web about `task` then have the AI actually answer. On error (AI off/missing key/lookup failed) -> None."""
        cfg = await AIConfigRepository(session).get(reminder.guild_id)
        if cfg is None or not cfg.enabled:
            return None
        raw = await run_web_search(task)
        low = raw.lower()
        # NOTE: these substrings are the failure sentinels returned by run_web_search
        # (in app/services/ai/tools/web_search.py) — "Web search failed.",
        # "No results found.", "Web search not configured ...". Keep them in sync with that
        # file; changing the wording there would silently break this check.
        if "failed" in low or "no results" in low or "not configured" in low:
            return None  # web lookup failed
        try:
            text = await _gateway(session).complete(
                guild_discord_id=channel.guild.id,
                system=build_reminder_task_system(cfg.persona, task),
                prompt=raw,
            )
        except ValueError:
            return None  # AI off / missing key / out of budget
        return text or None
