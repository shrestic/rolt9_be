# Cog that registers the moderation slash commands
# (/ban /kick /mute /unmute /unban /warn /warnings /case).
#
# The cog is a thin layer: parse the interaction → build an Actor → call
# ModerationService → reply. All business logic (DB writes, Discord actions,
# embed delivery) lives in ModerationService.
#
# Cogs ARE allowed to import discord for type hints on discord.Interaction /
# discord.Member (which the framework hands in) and for discord.app_commands
# (used to register slash commands). They MUST NOT make actions directly
# (guild.ban/kick/etc.) — those go through self.discord_io (DiscordClient).

import logging
from collections.abc import Awaitable, Callable

import discord
from discord import app_commands
from discord.ext import commands

from app.db.session import AsyncSessionLocal
from app.discord_io.client import DiscordClient
from app.discord_io.clients.bot import _to_discord_embed
from app.discord_io.errors import DiscordError
from app.repositories.guild import GuildRepository
from app.repositories.guild_settings import GuildSettingsRepository
from app.repositories.mod_case import ModCaseRepository
from app.services.moderation import Actor, ModerationService, build_case_embed

log = logging.getLogger(__name__)

# Suffix → seconds. Supports s/m/h/d.
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


# Parse "30m" / "2h" / "1d" / "45s" → seconds. Returns None for invalid format.
def _parse_duration(text: str) -> int | None:
    text = text.strip().lower()
    if not text or text[-1] not in _UNITS or not text[:-1].isdigit():
        return None
    return int(text[:-1]) * _UNITS[text[-1]]


# Build a ModerationService scoped to the given session. Each slash command
# opens its own session (the bot has no per-request scope like FastAPI does).
def _build_service(session, discord_io: DiscordClient) -> ModerationService:
    return ModerationService(
        session=session,
        discord_io=discord_io,
        guilds=GuildRepository(session),
        settings=GuildSettingsRepository(session),
        cases=ModCaseRepository(session),
    )


# Runs `action(service)` inside a fresh DB session and replies to the
# interaction. The wrapper handles three things every slash command needs:
#   1. defer() up front — slash commands have a 3-second deadline to ack.
#      Once deferred we have 15 minutes to followup, plenty for DB + Discord
#      calls.
#   2. catch the expected failure modes and reply with a friendly message
#      instead of letting the error bubble up (which would show the moderator
#      a generic "interaction failed").
#        - ValueError    → bad input (e.g. mute duration > 28 days)
#        - LookupError   → "no such thing" (guild not registered, user not banned)
#        - DiscordError  → Discord-side failure (permissions, rate limit, etc.)
async def _run_action(
    interaction: discord.Interaction,
    discord_io: DiscordClient,
    action: Callable[[ModerationService], Awaitable[str]],
) -> None:
    await interaction.response.defer(ephemeral=True)
    try:
        async with AsyncSessionLocal() as session:
            service = _build_service(session, discord_io)
            message = await action(service)
    except ValueError as exc:
        await interaction.followup.send(f"❌ {exc}", ephemeral=True)
        return
    except LookupError as exc:
        await interaction.followup.send(f"❌ {exc}", ephemeral=True)
        return
    except DiscordError as exc:
        log.warning("Discord action failed: %s", exc)
        await interaction.followup.send(
            f"❌ Discord rejected the action ({type(exc).__name__}). "
            f"The bot may lack permission or be rate-limited.",
            ephemeral=True,
        )
        return
    await interaction.followup.send(message, ephemeral=True)


class ModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot, discord_io: DiscordClient):
        self.bot = bot
        # self.discord_io is a DiscordClient (BotDiscordClient instance) — NOT
        # the discord SDK module. The name makes cog code read naturally:
        # `self.discord_io.ban_member(...)`.
        self.discord_io = discord_io

    @app_commands.command(name="ban", description="Ban a member")
    @app_commands.describe(member="Member to ban", reason="Reason")
    @app_commands.default_permissions(ban_members=True)
    async def ban(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str | None = None,
    ):
        async def do(service: ModerationService) -> str:
            case = await service.ban(
                guild_id=int(interaction.guild.id),
                target=Actor.from_member(member),
                moderator=Actor.from_member(interaction.user),
                reason=reason,
            )
            return f"Banned {member} — case #{case.case_number}"

        await _run_action(interaction, self.discord_io, do)

    @app_commands.command(name="kick", description="Kick a member")
    @app_commands.describe(member="Member to kick", reason="Reason")
    @app_commands.default_permissions(kick_members=True)
    async def kick(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str | None = None,
    ):
        async def do(service: ModerationService) -> str:
            case = await service.kick(
                guild_id=int(interaction.guild.id),
                target=Actor.from_member(member),
                moderator=Actor.from_member(interaction.user),
                reason=reason,
            )
            return f"Kicked {member} — case #{case.case_number}"

        await _run_action(interaction, self.discord_io, do)

    @app_commands.command(name="mute", description="Timeout a member (e.g. 30m, 2h, 1d)")
    @app_commands.describe(member="Member", duration="e.g. 30m, 2h, 1d", reason="Reason")
    @app_commands.default_permissions(moderate_members=True)
    async def mute(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        duration: str,
        reason: str | None = None,
    ):
        # Parse the duration string before we even defer — bad format is a
        # user-input error, not an action failure.
        seconds = _parse_duration(duration)
        if seconds is None or seconds <= 0:
            await interaction.response.send_message(
                "Invalid duration. Use e.g. 30m, 2h, 1d.", ephemeral=True
            )
            return

        async def do(service: ModerationService) -> str:
            case = await service.mute(
                guild_id=int(interaction.guild.id),
                target=Actor.from_member(member),
                moderator=Actor.from_member(interaction.user),
                reason=reason,
                duration_seconds=seconds,
            )
            return f"Muted {member} for {duration} — case #{case.case_number}"

        await _run_action(interaction, self.discord_io, do)

    @app_commands.command(name="unmute", description="Remove a member's timeout")
    @app_commands.describe(member="Member", reason="Reason")
    @app_commands.default_permissions(moderate_members=True)
    async def unmute(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str | None = None,
    ):
        async def do(service: ModerationService) -> str:
            case = await service.unmute(
                guild_id=int(interaction.guild.id),
                target=Actor.from_member(member),
                moderator=Actor.from_member(interaction.user),
                reason=reason,
            )
            return f"Unmuted {member} — case #{case.case_number}"

        await _run_action(interaction, self.discord_io, do)

    # /unban is special: only a user_id (string) is given, no Member object —
    # the banned user is no longer in the guild to be picked from autocomplete.
    @app_commands.command(name="unban", description="Unban a user by ID")
    @app_commands.describe(user_id="The user's Discord ID", reason="Reason")
    @app_commands.default_permissions(ban_members=True)
    async def unban(
        self, interaction: discord.Interaction, user_id: str, reason: str | None = None
    ):
        # Validate the id format upfront. Wrong format = user input error.
        try:
            uid = int(user_id)
        except ValueError:
            await interaction.response.send_message(
                "Invalid user ID — must be a number.", ephemeral=True
            )
            return

        async def do(service: ModerationService) -> str:
            # Resolve the username so the success message reads naturally.
            # If the user doesn't exist at all, DiscordNotFound bubbles up
            # and _run_action turns it into a friendly error.
            user_info = await self.discord_io.get_user(uid)
            case = await service.unban(
                guild_id=int(interaction.guild.id),
                target=Actor(user_id=user_info.discord_id, username=user_info.username),
                moderator=Actor.from_member(interaction.user),
                reason=reason,
            )
            return f"Unbanned {user_info.username} — case #{case.case_number}"

        await _run_action(interaction, self.discord_io, do)

    @app_commands.command(name="warn", description="Warn a member")
    @app_commands.describe(member="Member", reason="Reason")
    @app_commands.default_permissions(moderate_members=True)
    async def warn(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str | None = None,
    ):
        async def do(service: ModerationService) -> str:
            # service.warn returns a tuple: (warn_case, optional_escalation_case).
            # The escalation case is non-None only when the warn count hits a
            # threshold configured in settings.
            case, escalation = await service.warn(
                guild_id=int(interaction.guild.id),
                target=Actor.from_member(member),
                moderator=Actor.from_member(interaction.user),
                reason=reason,
            )
            msg = f"Warned {member} — case #{case.case_number}"
            if escalation is not None:
                msg += f" · auto-{escalation.action} applied " f"(case #{escalation.case_number})"
            return msg

        await _run_action(interaction, self.discord_io, do)

    # /warnings and /case are read-only queries — no Discord action — but we
    # still route them through the service for consistency (no cog should
    # reach past the service into repos directly).

    @app_commands.command(name="warnings", description="Show a member's active warning count")
    @app_commands.describe(member="Member")
    @app_commands.default_permissions(moderate_members=True)
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        async def do(service: ModerationService) -> str:
            count = await service.count_active_warns(
                guild_id=int(interaction.guild.id), user_id=int(member.id)
            )
            return f"{member} has {count} active warning(s)."

        await _run_action(interaction, self.discord_io, do)

    # /case posts a case embed ephemerally to the moderator. We must convert
    # Embed → discord.Embed because interaction.followup.send expects a
    # discord.Embed (this is a framework reply, not routed through DiscordClient).
    @app_commands.command(name="case", description="Look up a moderation case by number")
    @app_commands.describe(number="Case number")
    @app_commands.default_permissions(moderate_members=True)
    async def case(self, interaction: discord.Interaction, number: int):
        await interaction.response.defer(ephemeral=True)
        try:
            async with AsyncSessionLocal() as session:
                service = _build_service(session, self.discord_io)
                found = await service.get_case(
                    guild_id=int(interaction.guild.id), case_number=number
                )
        except LookupError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return
        if found is None:
            await interaction.followup.send("Case not found.", ephemeral=True)
            return
        await interaction.followup.send(
            embed=_to_discord_embed(build_case_embed(found)), ephemeral=True
        )
