"""Slash command for badges. Thin layer over BadgeService (mirrors CurrencyCog):
defer → session_scope → build service → list → render."""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from app.db.session import session_scope
from app.discord_io.client import DiscordClient
from app.repositories.badge_config import BadgeConfigRepository
from app.repositories.guild import GuildRepository
from app.repositories.user_badge import BadgeRepository
from app.repositories.user_wallet import WalletRepository
from app.repositories.user_xp import UserXpRepository
from app.services.badges import BadgeService

log = logging.getLogger(__name__)


def _build_service(session) -> BadgeService:
    """Wire up all repos the BadgeService needs from a single DB session.

    Mirrors the _build_service pattern in CurrencyCog and LevelingCog:
    one session → one service with all dependencies injected.
    """
    return BadgeService(
        guild_repo=GuildRepository(session),
        badge_repo=BadgeRepository(session),
        badge_config_repo=BadgeConfigRepository(session),
        xp_repo=UserXpRepository(session),
        wallet_repo=WalletRepository(session),
    )


class BadgesCog(commands.Cog):
    def __init__(self, bot: commands.Bot, discord_io: DiscordClient):
        self.bot = bot
        self.discord_io = discord_io

    @app_commands.command(name="badges", description="View your achievement badges.")
    @app_commands.guild_only()
    async def badges(
        self, interaction: discord.Interaction, member: discord.Member | None = None
    ) -> None:
        # Default to the invoker if no member is specified — lets users peek at
        # another member's badge shelf by passing @mention.
        target = member or interaction.user

        # Defer first (gives us up to 15 min to reply), then open the DB session.
        await interaction.response.defer()

        async with session_scope() as session:
            service = _build_service(session)
            # On-view catch-all: grant any badges the target has newly crossed
            # (e.g. wealth/streak thresholds reached since their last /daily)
            # before rendering, so /badges never shows an earned badge as locked.
            await service.award_new(guild_discord_id=interaction.guild_id, user_id=target.id)
            earned, locked, enabled = await service.list_for(
                guild_discord_id=interaction.guild_id, user_id=target.id
            )

        # Badges feature is toggled per-guild; short-circuit if it's off.
        if not enabled:
            await interaction.followup.send("Badges are turned off on this server.")
            return

        lines = [f"**{target.mention}'s badges**"]

        if earned:
            lines.append("\n🏅 **Earned**")
            # Each earned entry is (BadgeDef, datetime) — we show name + description
            # but not the earned timestamp to keep the message concise.
            lines += [f"{b.emoji} **{b.name}** — {b.description}" for b, _ in earned]
        else:
            # Motivational nudge when the member hasn't earned anything yet.
            lines.append("\nNo badges unlocked yet — keep chatting & checking in!")

        if locked:
            lines.append("\n🔒 **Locked**")
            # Locked badges shown without bold name — visually subdued vs earned.
            lines += [f"{b.emoji} {b.name} — {b.description}" for b in locked]

        await interaction.followup.send("\n".join(lines))
