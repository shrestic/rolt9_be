import logging

import discord
from discord.ext import commands

from app.bot.events import handle_guild_join, handle_guild_remove
from app.core.config import settings
from app.db.session import AsyncSessionLocal

log = logging.getLogger(__name__)


def build_bot() -> commands.Bot:
    intents = discord.Intents.none()
    intents.guilds = True  # only guild lifecycle

    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        log.info("Bot ready. Connected to %d guild(s).", len(bot.guilds))

    @bot.event
    async def on_guild_join(guild: discord.Guild):
        async with AsyncSessionLocal() as session:  # type: ignore
            await handle_guild_join(guild, session)

    @bot.event
    async def on_guild_remove(guild: discord.Guild):
        async with AsyncSessionLocal() as session:  # type: ignore
            await handle_guild_remove(guild, session)

    return bot


def run_bot() -> None:
    logging.basicConfig(level=logging.INFO)
    bot = build_bot()
    bot.run(settings.DISCORD_BOT_TOKEN)
