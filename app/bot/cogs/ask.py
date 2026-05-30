"""`/ask <question>` — answer from the guild knowledge base (AI).

Thin layer over AskService + AIGateway. 10s/user cooldown; AI/KB errors → ❌.
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
from app.repositories.kb import KbRepository
from app.services.ai.ai_gateway import AIGateway
from app.services.ai.ask_service import AskService
from app.services.ai.provider import get_ai_provider

log = logging.getLogger(__name__)


def _build_service(session) -> AskService:
    gateway = AIGateway(
        guild_repo=GuildRepository(session),
        config_repo=AIConfigRepository(session),
        usage_repo=AIUsageRepository(session),
        provider=get_ai_provider(),
    )
    return AskService(
        gateway=gateway,
        guild_repo=GuildRepository(session),
        kb_repo=KbRepository(session),
    )


class AskCog(commands.Cog):
    def __init__(self, bot: commands.Bot, discord_io: DiscordClient):
        self.bot = bot
        self.discord_io = discord_io

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            secs = round(error.retry_after, 1)
            msg = f"⏳ Hỏi gì lắm thế — đợi {secs}s nữa."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return
        raise error

    @app_commands.command(name="ask", description="Hỏi đáp dựa trên kho tri thức của server (AI).")
    @app_commands.describe(question="Câu hỏi của bạn")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 10.0)
    async def ask(self, interaction: discord.Interaction, question: str) -> None:
        await interaction.response.defer()
        try:
            async with session_scope() as session:
                answer = await _build_service(session).ask(
                    guild_discord_id=interaction.guild_id, question=question
                )
            await interaction.followup.send(f"❓ **{question}**\n💡 {answer}")
        except ValueError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
