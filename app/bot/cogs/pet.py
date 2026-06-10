"""Slash commands for the server pet — a `/pet` group with status/feed/play.

Thin layer over PetService (mirrors other cogs): defer → session_scope → build
service → act → reply. Service ValueErrors become a friendly ❌ message.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from app.db.session import session_scope
from app.discord_io.client import DiscordClient
from app.repositories.guild import GuildRepository
from app.repositories.pet import PetRepository
from app.repositories.pet_cooldown import PetCooldownRepository
from app.repositories.user_wallet import WalletRepository
from app.services.pet import PetService
from app.services.pet.pet_service import PetActionResult, PetStatus

log = logging.getLogger(__name__)


def _build_service(session) -> PetService:
    """Wire up all repos the PetService needs from a single DB session.

    Mirrors the _build_service pattern in QuestsCog and BadgesCog:
    one session → one service with all dependencies injected.
    """
    return PetService(
        guild_repo=GuildRepository(session),
        pet_repo=PetRepository(session),
        cooldown_repo=PetCooldownRepository(session),
        wallet_repo=WalletRepository(session),
    )


def _bar(value: int) -> str:
    """10-cell bar for a 0..100 stat, e.g. '▰▰▰▱▱▱▱▱▱▱ 30/100'.

    Each cell represents 10 points so users can read the rough percentage
    without squinting at the raw number.
    """
    filled = max(0, min(10, value // 10))
    return f"{'▰' * filled}{'▱' * (10 - filled)} {value}/100"


def _render(status: PetStatus) -> str:
    """Build a multi-line Discord message for the pet's current state.

    Shows name/level/stage on the first line, then two stat bars.
    Appends a nudge line if either stat is critically low (≤ 20).
    """
    lines = [
        f"{status.stage_emoji}{status.mood_emoji} **{status.name}** • Lv {status.level} "
        f"({status.stage_name})",
        f"🍖 Fed   {_bar(status.hunger)}",
        f"🎾 Happy {_bar(status.happiness)}",
    ]
    if status.hunger <= 20 or status.happiness <= 20:
        # Warn the user before stats bottom out and the pet gets sad.
        lines.append("\nYour pet needs some love — go feed it / play with it!")
    return "\n".join(lines)


def _growth_suffix(res: PetActionResult) -> str:
    """Return an extra celebration line if the pet leveled up or evolved.

    Evolution takes priority over a plain level-up message since it's
    the bigger event and includes the new stage name.
    """
    if res.evolved:
        return (
            f"\n✨ **{res.status.name}** evolved into "
            f"{res.status.stage_name} {res.status.stage_emoji}!"
        )
    if res.leveled_up:
        return f"\n🎉 **{res.status.name}** reached Lv {res.status.level}!"
    return ""


class PetCog(commands.Cog):
    def __init__(self, bot: commands.Bot, discord_io: DiscordClient):
        self.bot = bot
        self.discord_io = discord_io

    # Group all pet subcommands under `/pet` — guild_only so user IDs
    # are always scoped to a server (DMs have no guild_id).
    pet = app_commands.Group(name="pet", description="The server's pet", guild_only=True)

    @pet.command(name="status", description="View the server's pet.")
    async def pet_status(self, interaction: discord.Interaction) -> None:
        # Defer first (up to 15 min to reply), then open DB session.
        await interaction.response.defer()

        async with session_scope() as session:
            status = await _build_service(session).get_status(guild_discord_id=interaction.guild_id)

        # Short-circuit: pet feature disabled or not yet configured.
        if status is None or not status.enabled:
            await interaction.followup.send("This server hasn't enabled the pet yet.")
            return

        await interaction.followup.send(_render(status))

    @pet.command(name="feed", description="Feed the pet (costs coins).")
    async def pet_feed(self, interaction: discord.Interaction) -> None:
        # Defer first, then attempt to feed inside a DB session.
        await interaction.response.defer()
        try:
            async with session_scope() as session:
                res = await _build_service(session).feed(
                    guild_discord_id=interaction.guild_id, user_id=interaction.user.id
                )
            # Show new hunger stat and remaining balance so the user knows the cost.
            msg = (
                f"🍖 Fed {res.status.name}! Fed: **{res.status.hunger}/100** "
                f"(balance {res.balance:,} 🪙)"
            ) + _growth_suffix(res)
            await interaction.followup.send(msg)
        except ValueError as exc:
            # Service raises ValueError for: pet disabled, insufficient coins, cooldown.
            # Ephemeral so the error is private — no need to clutter the channel.
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)

    @pet.command(name="play", description="Play with the pet (free).")
    async def pet_play(self, interaction: discord.Interaction) -> None:
        # Defer first, then attempt to play inside a DB session.
        await interaction.response.defer()
        try:
            async with session_scope() as session:
                res = await _build_service(session).play(
                    guild_discord_id=interaction.guild_id, user_id=interaction.user.id
                )
            msg = f"🎾 Played with {res.status.name}! Happy: **{res.status.happiness}/100**"
            msg += _growth_suffix(res)
            await interaction.followup.send(msg)
        except ValueError as exc:
            # Service raises ValueError for: pet disabled, cooldown not expired.
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
