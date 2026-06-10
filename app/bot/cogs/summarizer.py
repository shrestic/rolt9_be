"""`/summarize [count]` — AI summarizes the N most recent messages in the channel.

The cog fetches channel history (it has the live interaction.channel), builds a
transcript, and hands it to SummarizerService (which calls the AIGateway). 15s/user
cooldown to bound token spend; AI errors → friendly ❌.
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
from app.services.ai.summarizer_service import SummarizerService

log = logging.getLogger(__name__)

MAX_COUNT = 100
DEFAULT_COUNT = 30


def _build_service(session) -> SummarizerService:
    gateway = AIGateway(
        guild_repo=GuildRepository(session),
        config_repo=AIConfigRepository(session),
        usage_repo=AIUsageRepository(session),
        provider=get_ai_provider(),
    )
    return SummarizerService(gateway=gateway)


async def _collect_transcript(channel, limit: int) -> str:
    """Read up to `limit` recent messages, oldest→newest, skipping bots/empties."""
    lines: list[str] = []
    async for msg in channel.history(limit=limit):
        if getattr(msg.author, "bot", False):
            continue
        content = (msg.content or "").strip()
        if not content:
            continue
        name = getattr(msg.author, "display_name", str(msg.author))
        lines.append(f"{name}: {content}")
    lines.reverse()  # history yields newest-first; transcript reads oldest-first
    return "\n".join(lines)


class SummarizerCog(commands.Cog):
    def __init__(self, bot: commands.Bot, discord_io: DiscordClient):
        self.bot = bot
        self.discord_io = discord_io

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            secs = round(error.retry_after, 1)
            msg = f"⏳ So many summaries — wait {secs}s more."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return
        raise error

    @app_commands.command(name="summarize", description="Summarize recent messages (AI).")
    @app_commands.describe(count="Number of recent messages to summarize (default 30, max 100)")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 15.0)
    async def summarize(self, interaction: discord.Interaction, count: int = DEFAULT_COUNT) -> None:
        count = max(1, min(MAX_COUNT, count))
        await interaction.response.defer()
        transcript = await _collect_transcript(interaction.channel, count)
        if not transcript:
            await interaction.followup.send("No messages to summarize.")
            return
        try:
            async with session_scope() as session:
                summary = await _build_service(session).summarize(
                    guild_discord_id=interaction.guild_id, transcript=transcript
                )
            await interaction.followup.send(
                f"📝 **Summary of the last {count} messages:**\n{summary}"
            )
        except ValueError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
