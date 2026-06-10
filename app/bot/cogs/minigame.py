"""Slash commands for mini-games — a `/game` group: flip / over_under / slots.

Thin layer over MinigameService. Each command has a 3s/user cooldown
(`app_commands.checks.cooldown`); the cooldown error is rendered by
`cog_app_command_error`. Service ValueErrors (disabled, bad bet, no funds)
become a friendly ❌ message.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from app.db.session import session_scope
from app.discord_io.client import DiscordClient
from app.repositories.guild import GuildRepository
from app.repositories.minigame_config import MinigameConfigRepository
from app.repositories.user_wallet import WalletRepository
from app.services.minigames import MinigameService

log = logging.getLogger(__name__)


def _build_service(session) -> MinigameService:
    return MinigameService(
        guild_repo=GuildRepository(session),
        config_repo=MinigameConfigRepository(session),
        wallet_repo=WalletRepository(session),
    )


def _render(result) -> str:
    """Shape a GameResult into the reply line (win shows +net, loss shows -bet)."""
    if result.won:
        head = f"🎉 You won! +**{result.net:,}** 🪙"
    else:
        head = f"😢 You lost **{abs(result.net):,}** 🪙"
    return f"{result.detail} — {head} (balance {result.balance:,})"


class MinigameCog(commands.Cog):
    def __init__(self, bot: commands.Bot, discord_io: DiscordClient):
        self.bot = bot
        self.discord_io = discord_io

    game = app_commands.Group(name="game", description="Coin betting mini-games", guild_only=True)

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        """Render the per-command cooldown error nicely; re-raise anything else."""
        if isinstance(error, app_commands.CommandOnCooldown):
            secs = round(error.retry_after, 1)
            msg = f"⏳ Slow down — wait {secs}s."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return
        raise error

    @game.command(name="flip", description="Flip a coin (bet coins).")
    @app_commands.describe(bet="Coins to bet", choice="Pick a side")
    @app_commands.choices(
        choice=[
            app_commands.Choice(name="Heads", value="heads"),
            app_commands.Choice(name="Tails", value="tails"),
        ]
    )
    @app_commands.checks.cooldown(1, 3.0)
    async def game_flip(self, interaction: discord.Interaction, bet: int, choice: str) -> None:
        await interaction.response.defer()
        try:
            async with session_scope() as session:
                res = await _build_service(session).play_coinflip(
                    guild_discord_id=interaction.guild_id,
                    user_id=interaction.user.id,
                    bet=bet,
                    choice=choice,
                )
            await interaction.followup.send(_render(res))
        except ValueError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)

    @game.command(name="overunder", description="Over/under with 3 dice (bet coins).")
    @app_commands.describe(bet="Coins to bet", choice="Over (≥11) or Under (≤10)")
    @app_commands.choices(
        choice=[
            app_commands.Choice(name="Over", value="over"),
            app_commands.Choice(name="Under", value="under"),
        ]
    )
    @app_commands.checks.cooldown(1, 3.0)
    async def game_over_under(
        self, interaction: discord.Interaction, bet: int, choice: str
    ) -> None:
        await interaction.response.defer()
        try:
            async with session_scope() as session:
                res = await _build_service(session).play_over_under(
                    guild_discord_id=interaction.guild_id,
                    user_id=interaction.user.id,
                    bet=bet,
                    choice=choice,
                )
            await interaction.followup.send(_render(res))
        except ValueError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)

    @game.command(name="slots", description="Spin the slots (bet coins).")
    @app_commands.describe(bet="Coins to bet")
    @app_commands.checks.cooldown(1, 3.0)
    async def game_slots(self, interaction: discord.Interaction, bet: int) -> None:
        await interaction.response.defer()
        try:
            async with session_scope() as session:
                res = await _build_service(session).play_slots(
                    guild_discord_id=interaction.guild_id,
                    user_id=interaction.user.id,
                    bet=bet,
                )
            await interaction.followup.send(_render(res))
        except ValueError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
