"""`/chat <message>` — talk to the bot in the server's AI persona.

Thin layer over ChatService + AIGateway. 8s/user cooldown; AI errors → ❌.
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
from app.services.ai.chat_service import ChatService
from app.services.ai.provider import get_ai_provider

log = logging.getLogger(__name__)


def _build_service(session) -> ChatService:
    gateway = AIGateway(
        guild_repo=GuildRepository(session),
        config_repo=AIConfigRepository(session),
        usage_repo=AIUsageRepository(session),
        provider=get_ai_provider(),
    )
    return ChatService(
        gateway=gateway,
        guild_repo=GuildRepository(session),
        config_repo=AIConfigRepository(session),
    )


class ChatCog(commands.Cog):
    def __init__(self, bot: commands.Bot, discord_io: DiscordClient):
        self.bot = bot
        self.discord_io = discord_io

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            secs = round(error.retry_after, 1)
            msg = f"⏳ Chờ chút — đợi {secs}s nữa."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return
        raise error

    @app_commands.command(name="chat", description="Trò chuyện với bot (AI, theo cá tính server).")
    @app_commands.describe(message="Lời nhắn của bạn")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 8.0)
    async def chat(self, interaction: discord.Interaction, message: str) -> None:
        await interaction.response.defer()
        try:
            async with session_scope() as session:
                reply = await _build_service(session).chat(
                    guild_discord_id=interaction.guild_id, message=message
                )
            await interaction.followup.send(reply)
        except ValueError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
