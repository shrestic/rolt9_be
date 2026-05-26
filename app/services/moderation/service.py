# ModerationService — the single entry point from a cog (bot) or an endpoint
# (REST) into the moderation business logic. Internally each public method:
#   1. Loads the guild row + mod_settings from the DB
#   2. Calls DiscordClient to perform the action (ban/kick/mute/unmute/unban)
#   3. Writes a mod_case row to the DB
#   4. Delivers (mod-log post + target DM) via delivery.deliver_case
#   5. Returns the ModCase row
#
# The service knows nothing about discord.py or httpx. Discord calls go through
# DiscordClient; DB calls go through repositories. It can be tested with a
# FakeDiscordClient + an in-memory DB.

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.discord_io.client import DiscordClient
from app.models.guild import Guild
from app.models.mod_case import ModCase
from app.repositories.guild import GuildRepository
from app.repositories.guild_settings import GuildSettingsRepository
from app.repositories.mod_case import ModCaseRepository
from app.services.moderation.actor import Actor
from app.services.moderation.delivery import deliver_case
from app.services.moderation.escalation import next_escalation

# Discord caps timeouts at 28 days; longer requests get rejected with HTTP 400.
# We validate up-front and surface a clear ValueError instead of a vague API error.
MAX_TIMEOUT_SECONDS = 28 * 86400

# Process-wide locks keyed by (guild_id, target_user_id). They serialize the
# /warn flow so two moderators warning the same user at the same time can't
# both miss (or both fire) the escalation rule. Held only across one warn
# operation, then sits idle in the dict — memory is bounded by distinct
# (guild, target) pairs ever warned.
_warn_locks: dict[tuple[int, int], asyncio.Lock] = {}


def _warn_lock_for(guild_id: int, user_id: int) -> asyncio.Lock:
    key = (guild_id, user_id)
    lock = _warn_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _warn_locks[key] = lock
    return lock


class ModerationService:
    def __init__(
        self,
        session: AsyncSession,
        discord_io: DiscordClient,
        guilds: GuildRepository,
        settings: GuildSettingsRepository,
        cases: ModCaseRepository,
    ):
        self.session = session
        self.discord_io = discord_io
        self.guilds = guilds
        self.settings = settings
        self.cases = cases

    # ─────────────────────────────────────────────────────────────────────
    # Public actions — every method follows the same 4 steps:
    #   load → discord → DB → deliver
    # ─────────────────────────────────────────────────────────────────────

    async def ban(
        self,
        *,
        guild_id: int,
        target: Actor,
        moderator: Actor,
        reason: str | None,
    ) -> ModCase:
        # 1. Load the guild ORM row + mod settings.
        guild_row, mod_settings = await self._load_guild_and_settings(guild_id)
        # 2. Ban on Discord.
        await self.discord_io.ban_member(guild_id, target.user_id, reason)
        # 3. Record the case in the DB.
        case = await self._record(
            guild_row=guild_row,
            action="ban",
            source="manual",
            target=target,
            moderator=moderator,
            reason=reason,
        )
        # 4. Post mod-log + DM (best-effort).
        await deliver_case(
            self.discord_io,
            guild_name=guild_row.name,
            mod_settings=mod_settings,
            target_user_id=target.user_id,
            case=case,
        )
        return case

    async def kick(
        self,
        *,
        guild_id: int,
        target: Actor,
        moderator: Actor,
        reason: str | None,
    ) -> ModCase:
        guild_row, mod_settings = await self._load_guild_and_settings(guild_id)
        await self.discord_io.kick_member(guild_id, target.user_id, reason)
        case = await self._record(
            guild_row=guild_row,
            action="kick",
            source="manual",
            target=target,
            moderator=moderator,
            reason=reason,
        )
        await deliver_case(
            self.discord_io,
            guild_name=guild_row.name,
            mod_settings=mod_settings,
            target_user_id=target.user_id,
            case=case,
        )
        return case

    async def mute(
        self,
        *,
        guild_id: int,
        target: Actor,
        moderator: Actor,
        reason: str | None,
        duration_seconds: int,
    ) -> ModCase:
        # Cap upfront so the moderator gets a clear error instead of a Discord 400.
        if duration_seconds > MAX_TIMEOUT_SECONDS:
            raise ValueError(
                f"Mute duration cannot exceed {MAX_TIMEOUT_SECONDS // 86400} days "
                f"(Discord limit)."
            )
        guild_row, mod_settings = await self._load_guild_and_settings(guild_id)
        # Discord takes an absolute timestamp; compute it from now + duration.
        until = datetime.now(UTC) + timedelta(seconds=duration_seconds)
        await self.discord_io.mute_member_until(guild_id, target.user_id, until, reason)
        case = await self._record(
            guild_row=guild_row,
            action="mute",
            source="manual",
            target=target,
            moderator=moderator,
            reason=reason,
            duration_seconds=duration_seconds,
            expires_at=until,
        )
        await deliver_case(
            self.discord_io,
            guild_name=guild_row.name,
            mod_settings=mod_settings,
            target_user_id=target.user_id,
            case=case,
        )
        return case

    async def unmute(
        self,
        *,
        guild_id: int,
        target: Actor,
        moderator: Actor,
        reason: str | None,
    ) -> ModCase:
        guild_row, mod_settings = await self._load_guild_and_settings(guild_id)
        await self.discord_io.unmute_member(guild_id, target.user_id, reason)
        case = await self._record(
            guild_row=guild_row,
            action="unmute",
            source="manual",
            target=target,
            moderator=moderator,
            reason=reason,
        )
        await deliver_case(
            self.discord_io,
            guild_name=guild_row.name,
            mod_settings=mod_settings,
            target_user_id=target.user_id,
            case=case,
        )
        return case

    async def unban(
        self,
        *,
        guild_id: int,
        target: Actor,
        moderator: Actor,
        reason: str | None,
    ) -> ModCase:
        guild_row, mod_settings = await self._load_guild_and_settings(guild_id)
        # Pre-check so we don't record a misleading "unban" case for a user
        # who was never banned. Costs one extra REST/cache lookup but keeps
        # the mod-log honest.
        if not await self.discord_io.is_banned(guild_id, target.user_id):
            raise LookupError(f"User {target.user_id} is not currently banned.")
        await self.discord_io.revoke_ban(guild_id, target.user_id, reason)
        case = await self._record(
            guild_row=guild_row,
            action="unban",
            source="manual",
            target=target,
            moderator=moderator,
            reason=reason,
        )
        await deliver_case(
            self.discord_io,
            guild_name=guild_row.name,
            mod_settings=mod_settings,
            target_user_id=target.user_id,
            case=case,
        )
        return case

    # /warn is more involved because of auto-escalation. Returns a tuple:
    #   (warn_case, escalation_case_or_None)
    # The escalation case is non-None only when the warn count hits a threshold
    # configured in settings.warn_escalation.
    async def warn(
        self,
        *,
        guild_id: int,
        target: Actor,
        moderator: Actor,
        reason: str | None,
    ) -> tuple[ModCase, ModCase | None]:
        # Serialize per (guild, target) so two concurrent /warn calls can't
        # race the count→escalate sequence (either both miss the threshold or
        # both fire). The lock is process-local — fine because we run as one
        # process. If we ever shard, swap to a PG advisory lock.
        async with _warn_lock_for(guild_id, target.user_id):
            return await self._warn_locked(
                guild_id=guild_id, target=target, moderator=moderator, reason=reason
            )

    async def _warn_locked(
        self,
        *,
        guild_id: int,
        target: Actor,
        moderator: Actor,
        reason: str | None,
    ) -> tuple[ModCase, ModCase | None]:
        guild_row, mod_settings = await self._load_guild_and_settings(guild_id)

        # Warn doesn't call any Discord action — just record the case + deliver
        # the embed.
        case = await self._record(
            guild_row=guild_row,
            action="warn",
            source="manual",
            target=target,
            moderator=moderator,
            reason=reason,
        )
        await deliver_case(
            self.discord_io,
            guild_name=guild_row.name,
            mod_settings=mod_settings,
            target_user_id=target.user_id,
            case=case,
        )

        # Count active warns for the target and check the escalation rules.
        count = await self.cases.active_warn_count(guild_row.id, target.user_id)
        rule = next_escalation(count, mod_settings.get("warn_escalation", []))
        if rule is None:
            return case, None

        # Escalation runs as AutoMod, not a human moderator.
        automod = Actor(user_id=0, username="AutoMod")

        if rule.get("action") == "mute":
            # Clamp the configured duration to Discord's 28-day max — admin
            # may have entered something larger.
            duration = min(int(rule.get("duration_seconds", 3600)), MAX_TIMEOUT_SECONDS)
            until = datetime.now(UTC) + timedelta(seconds=duration)
            await self.discord_io.mute_member_until(
                guild_id, target.user_id, until, "Warn escalation"
            )
            esc = await self._record(
                guild_row=guild_row,
                action="mute",
                source="escalation",
                target=target,
                moderator=automod,
                reason="Automatic: warn threshold reached",
                duration_seconds=duration,
                expires_at=until,
            )
        elif rule.get("action") == "ban":
            await self.discord_io.ban_member(guild_id, target.user_id, "Warn escalation")
            esc = await self._record(
                guild_row=guild_row,
                action="ban",
                source="escalation",
                target=target,
                moderator=automod,
                reason="Automatic: warn threshold reached",
            )
        else:
            # Invalid rule action (e.g. "kick" is not supported yet). Silently
            # return None for the escalation.
            return case, None

        # Deliver the escalation case separately (its own mod-log post + DM).
        await deliver_case(
            self.discord_io,
            guild_name=guild_row.name,
            mod_settings=mod_settings,
            target_user_id=target.user_id,
            case=esc,
        )
        return case, esc

    # DELETE /cases/{n} endpoint → deactivate the case in the DB and undo the
    # corresponding Discord state when it makes sense:
    #   - ban  → revoke the ban
    #   - mute → clear the timeout (otherwise the user stays muted until expiry)
    #   - kick / unmute / unban / warn → record-only; nothing to undo on Discord
    # The endpoint checks 404 before calling this, so we only receive an
    # already-existing case. Both Discord ops are idempotent in the adapter.
    async def deactivate_case(self, *, guild_id: int, case: ModCase) -> ModCase:
        if case.action == "ban":
            await self.discord_io.revoke_ban(guild_id, int(case.target_user_id))
        elif case.action == "mute":
            await self.discord_io.unmute_member(
                guild_id, int(case.target_user_id), "Case deactivated"
            )
        await self.cases.deactivate(case)
        return case

    # ─────────────────────────────────────────────────────────────────────
    # Public queries — exposed so cogs and endpoints don't reach past the
    # service into repos directly.
    # ─────────────────────────────────────────────────────────────────────

    # Active warn count for a user in a guild. Used by /warnings cog command.
    # Returns 0 when the guild isn't registered yet (race-safe for new guilds).
    async def count_active_warns(self, *, guild_id: int, user_id: int) -> int:
        guild_row = await self.guilds.get_by_discord_id(guild_id)
        if guild_row is None:
            return 0
        return await self.cases.active_warn_count(guild_row.id, user_id)

    # Look up one case by guild + case number. Used by the /case cog command
    # and by the GET /cases/{n} endpoint. Returns None when not found.
    async def get_case(self, *, guild_id: int, case_number: int) -> ModCase | None:
        guild_row = await self.guilds.get_by_discord_id(guild_id)
        if guild_row is None:
            return None
        return await self.cases.get_by_case_number(guild_row.id, case_number)

    # ─────────────────────────────────────────────────────────────────────
    # Internals
    # ─────────────────────────────────────────────────────────────────────

    # Load the Guild row + mod_settings dict in one helper since every action
    # needs them. Raises LookupError if the guild hasn't been registered
    # (e.g. the bot was just invited and the handle_guild_join event hasn't
    # fired yet — a rare race). LookupError, not DiscordNotFound, because the
    # missing data is in OUR DB, not on Discord's side.
    async def _load_guild_and_settings(self, guild_id: int) -> tuple[Guild, dict]:
        guild_row = await self.guilds.get_by_discord_id(guild_id)
        if guild_row is None:
            raise LookupError(f"Guild {guild_id} is not registered in this bot.")
        gs = await self.settings.get(guild_row.id)
        mod_settings = (gs.moderation if gs else {}) or {}
        return guild_row, mod_settings

    # Insert one mod_case row. Thin wrapper over the repo to keep service code
    # less verbose.
    async def _record(
        self,
        *,
        guild_row: Guild,
        action: str,
        source: str,
        target: Actor,
        moderator: Actor,
        reason: str | None,
        duration_seconds: int | None = None,
        expires_at: datetime | None = None,
    ) -> ModCase:
        return await self.cases.create_case(
            guild_id=guild_row.id,
            action=action,
            source=source,
            target_user_id=target.user_id,
            target_username=target.username,
            moderator_user_id=moderator.user_id,
            moderator_username=moderator.username,
            reason=reason,
            duration_seconds=duration_seconds,
            expires_at=expires_at,
        )
