"""Slash commands for quests — a `/quests` group with `list` and `claim`.

Thin layer over QuestService (mirrors other cogs): defer → session_scope →
build service → act → reply. Claim is claim-all (no ID typing in Discord).
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from app.db.session import session_scope
from app.discord_io.client import DiscordClient
from app.repositories.guild import GuildRepository
from app.repositories.quest import QuestRepository
from app.repositories.quest_progress import QuestProgressRepository
from app.repositories.user_wallet import WalletRepository
from app.services.quests import QuestService

log = logging.getLogger(__name__)


def _build_service(session) -> QuestService:
    """Wire up all repos the QuestService needs from a single DB session.

    Mirrors the _build_service pattern in BadgesCog and CurrencyCog:
    one session → one service with all dependencies injected.
    """
    return QuestService(
        guild_repo=GuildRepository(session),
        quest_repo=QuestRepository(session),
        progress_repo=QuestProgressRepository(session),
        wallet_repo=WalletRepository(session),
    )


def _bar(progress: int, target: int) -> str:
    """A tiny 10-cell progress bar, e.g. '██████░░░░ 60/100'.

    Renders a visual indicator for quest completion so users can see
    at a glance how close they are without reading raw numbers.
    """
    filled = 0 if target <= 0 else min(10, (progress * 10) // target)
    return f"{'█' * filled}{'░' * (10 - filled)} {min(progress, target)}/{target}"


class QuestsCog(commands.Cog):
    def __init__(self, bot: commands.Bot, discord_io: DiscordClient):
        self.bot = bot
        self.discord_io = discord_io

    # Group all quest subcommands under `/quests` — guild_only so user IDs
    # are always scoped to a server (DMs have no guild_id).
    quests = app_commands.Group(name="quests", description="Daily/weekly quests", guild_only=True)

    @quests.command(name="list", description="View quests and progress.")
    async def quests_list(self, interaction: discord.Interaction) -> None:
        # Defer first (up to 15 min to reply), then open DB session.
        await interaction.response.defer()

        async with session_scope() as session:
            views = await _build_service(session).list_quests(
                guild_discord_id=interaction.guild_id, user_id=interaction.user.id
            )

        # Short-circuit: server hasn't configured any quests yet.
        if not views:
            await interaction.followup.send("This server has no quests yet.")
            return

        lines = ["**📜 Quests**"]
        for v in views:
            # Tag label distinguishes daily vs weekly quests at a glance.
            tag = "daily" if v.quest.period == "daily" else "weekly"

            if v.claimed:
                # Already collected this period — show ticked checkbox.
                status = "☑️ Claimed"
            elif v.completed:
                # Completed but not yet claimed — highlight reward to prompt /claim.
                status = f"✅ Ready (+{v.quest.reward_coins:,} 🪙)"
            else:
                # In-progress — show visual bar so users know how far they are.
                status = _bar(v.progress, v.target)

            lines.append(f"`{tag}` **{v.quest.name}** — {status}")

        lines.append("\nType `/quests claim` to grab your rewards.")
        await interaction.followup.send("\n".join(lines))

    @quests.command(name="claim", description="Claim rewards for completed quests.")
    async def quests_claim(self, interaction: discord.Interaction) -> None:
        # Defer first, then claim-all completed quests in one DB transaction.
        await interaction.response.defer()

        async with session_scope() as session:
            result = await _build_service(session).claim(
                guild_discord_id=interaction.guild_id, user_id=interaction.user.id
            )

        # Nothing ready to collect — nudge user to complete quests first.
        if result.claimed_count == 0:
            await interaction.followup.send("No quests are ready to claim yet.")
            return

        # Success: show total coins earned and which quests were completed.
        joined = ", ".join(result.names)
        await interaction.followup.send(
            f"🎉 Claimed **{result.claimed_count}** quests: +**{result.total_coins:,}** 🪙! ({joined})"
        )
