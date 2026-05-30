"""Slash commands for karma — a `/karma` group with give/view/top.

Thin layer over KarmaService (mirrors other cogs). Self/bot recipients are
rejected here before hitting the service; service ValueErrors (disabled,
cooldown) become a friendly ❌ message.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from app.db.session import session_scope
from app.discord_io.client import DiscordClient
from app.repositories.guild import GuildRepository
from app.repositories.karma import KarmaRepository
from app.repositories.karma_config import KarmaConfigRepository
from app.repositories.karma_grant import KarmaGrantRepository
from app.services.karma import KarmaService

log = logging.getLogger(__name__)


def _build_service(session) -> KarmaService:
    """Wire up all repos the KarmaService needs from a single DB session.

    Mirrors the _build_service pattern in PetCog and other cogs:
    one session → one service with all dependencies injected.
    """
    return KarmaService(
        guild_repo=GuildRepository(session),
        karma_repo=KarmaRepository(session),
        grant_repo=KarmaGrantRepository(session),
        config_repo=KarmaConfigRepository(session),
    )


class KarmaCog(commands.Cog):
    def __init__(self, bot: commands.Bot, discord_io: DiscordClient):
        self.bot = bot
        self.discord_io = discord_io

    # Group all karma subcommands under `/karma` — guild_only so user IDs
    # are always scoped to a server (DMs have no guild_id).
    karma = app_commands.Group(name="karma", description="Điểm uy tín cộng đồng", guild_only=True)

    @karma.command(name="give", description="Trao 1 karma cho thành viên.")
    async def karma_give(self, interaction: discord.Interaction, member: discord.Member) -> None:
        # Defer first so the interaction doesn't time out while we hit the DB.
        await interaction.response.defer()

        # Cog-level guard: bots can't hold karma (they don't have intent).
        if member.bot:
            await interaction.followup.send("❌ Không thể trao karma cho bot.", ephemeral=True)
            return

        # Cog-level guard: self-voting is meaningless and gamed easily.
        if member.id == interaction.user.id:
            await interaction.followup.send("❌ Bạn không thể tự khen mình.", ephemeral=True)
            return

        try:
            async with session_scope() as session:
                res = await _build_service(session).give(
                    guild_discord_id=interaction.guild_id,
                    giver_id=interaction.user.id,
                    receiver_id=member.id,
                )
            # Show receiver's new total and rank so the kudos feel meaningful.
            await interaction.followup.send(
                f"⭐ +1 karma cho {member.mention}! Họ có **{res.receiver_points}** karma "
                f"(hạng #{res.receiver_rank})."
            )
        except ValueError as exc:
            # Service raises ValueError for: karma disabled, cooldown not expired.
            # Ephemeral so the error is private — no need to clutter the channel.
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)

    @karma.command(name="view", description="Xem karma của bạn hoặc người khác.")
    async def karma_view(
        self, interaction: discord.Interaction, member: discord.Member | None = None
    ) -> None:
        # Default to the caller if no member is specified.
        target = member or interaction.user
        await interaction.response.defer()

        async with session_scope() as session:
            standing = await _build_service(session).get_standing(
                guild_discord_id=interaction.guild_id, user_id=target.id
            )

        # Rank is None when the user has never received karma (no row yet).
        rank = f" (hạng #{standing.rank})" if standing.rank else ""
        await interaction.followup.send(
            f"⭐ {target.mention} có **{standing.points}** karma{rank}."
        )

    @karma.command(name="top", description="Bảng xếp hạng karma.")
    async def karma_top(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        async with session_scope() as session:
            rows, _ = await _build_service(session).leaderboard(
                guild_discord_id=interaction.guild_id, limit=10, offset=0
            )

        if not rows:
            await interaction.followup.send("Chưa ai có karma.")
            return

        # Format each row as "#{rank} @mention — N ⭐" for easy scanning.
        lines = [f"**#{i + 1}** <@{r.user_id}> — {r.points} ⭐" for i, r in enumerate(rows)]
        await interaction.followup.send("\n".join(lines))
