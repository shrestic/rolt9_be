"""`/roast @member` — AI cà khịa. Thin layer over RoastService + AIGateway.

10s/user cooldown to bound AI cost; bot targets rejected. Service ValueErrors
(AI off, no key, over budget) become a friendly ❌ message.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from app.db.session import session_scope
from app.discord_io.client import DiscordClient
from app.repositories.ai_config import AIConfigRepository
from app.repositories.ai_usage import AIUsageRepository
from app.repositories.guild import GuildRepository
from app.services.ai.ai_gateway import AIGateway
from app.services.ai.provider import get_ai_provider
from app.services.ai.roast_service import RoastService

log = logging.getLogger(__name__)


def _build_service(session) -> RoastService:
    gateway = AIGateway(
        guild_repo=GuildRepository(session),
        config_repo=AIConfigRepository(session),
        usage_repo=AIUsageRepository(session),
        provider=get_ai_provider(),
    )
    return RoastService(gateway=gateway)


class RoastCog(commands.Cog):
    def __init__(self, bot: commands.Bot, discord_io: DiscordClient):
        self.bot = bot
        self.discord_io = discord_io

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            secs = round(error.retry_after, 1)
            msg = f"⏳ Cà khịa gì lắm thế — đợi {secs}s nữa."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return
        raise error

    @app_commands.command(name="roast", description="Cà khịa một thành viên (AI).")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 10.0)
    async def roast(self, interaction: discord.Interaction, member: discord.Member) -> None:
        if member.bot:
            await interaction.response.send_message("❌ Bot thì cà khịa gì nữa.", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            async with session_scope() as session:
                text = await _build_service(session).roast(
                    guild_discord_id=interaction.guild_id, target_name=member.display_name
                )
            await interaction.followup.send(f"🔥 {member.mention} {text}")
        except ValueError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
