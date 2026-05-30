# Bot construction. This file:
#   1. Defines Rolt9Bot (subclass of discord.ext.commands.Bot)
#   2. Constructs BotDiscordClient and injects it into the cogs at setup
#   3. Registers event handlers (on_ready, on_guild_join, on_guild_remove) —
#      each handler converts discord.Guild → GuildInfo before calling events.py
#
# The bot is started by app/main.py's lifespan, in the SAME process as FastAPI.
# `build_bot()` is the only thing exposed; lifespan does `bot.start(...)` itself.
#
# One of the few files outside app/discord/clients/ allowed to import discord —
# because we need to subclass commands.Bot (framework integration), not for
# any SDK action.

import logging

import discord
from discord.ext import commands

from app.bot.cache.guild_config_cache import GuildConfigCache
from app.bot.cache.leveling_config_cache import LevelingConfigCache
from app.bot.cogs.badges import BadgesCog
from app.bot.cogs.currency import CurrencyCog
from app.bot.cogs.custom_commands import CustomCommandsCog
from app.bot.cogs.karma import KarmaCog
from app.bot.cogs.leveling import LevelingCog
from app.bot.cogs.minigame import MinigameCog
from app.bot.cogs.moderation import ModerationCog
from app.bot.cogs.pet import PetCog
from app.bot.cogs.quests import QuestsCog
from app.bot.cogs.roast import RoastCog
from app.bot.cogs.xp_decay import XpDecayCog
from app.bot.events import (
    handle_guild_join,
    handle_guild_remove,
    handle_guild_update,
    handle_ready,
)
from app.bot.listeners.xp_listener import XpListenerCog
from app.db.session import session_scope
from app.discord_io.client import DiscordClient
from app.discord_io.clients.bot import BotDiscordClient
from app.discord_io.types import GuildInfo

log = logging.getLogger(__name__)


# Convert discord.Guild (SDK) → GuildInfo (our dataclass). Only used in the
# event boundary so events.py can stay free of discord imports.
def _guild_info_from(guild: discord.Guild) -> GuildInfo:
    icon_url = guild.icon.url if guild.icon else None
    return GuildInfo(
        discord_id=int(guild.id),
        name=guild.name,
        icon_url=icon_url,
        member_count=int(getattr(guild, "member_count", 0) or 0),
    )


class Rolt9Bot(commands.Bot):
    def __init__(self):
        # Intents = privilege bits the bot requests from Discord. Fewer = faster.
        # We currently need:
        #   - guilds: to receive on_guild_join / on_guild_remove / on_ready
        #   - guild_messages: to receive on_message events in server channels.
        #     WITHOUT this, Discord doesn't dispatch MESSAGE_CREATE at all, so
        #     the custom-command cog never sees "!hi" messages — even with the
        #     message_content intent enabled. (message_content only controls
        #     whether `message.content` is non-empty; the event itself is gated
        #     by guild_messages.)
        #   - message_content: privileged intent that fills in `message.content`
        #     so the cog can match the command trigger. Must ALSO be enabled
        #     in the Discord Developer Portal under "Privileged Gateway Intents".
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True

        super().__init__(command_prefix="!", intents=intents, help_command=None)

        # In-memory cache for GuildConfig (custom commands + settings).
        # CustomCommandsCog uses this instead of querying the DB for every message.
        self.config_cache = GuildConfigCache()
        self.leveling_config_cache = LevelingConfigCache()

        # One DiscordClient instance shared across all cogs. Constructed here
        # (after super().__init__) because BotDiscordClient needs `self` (the
        # commands.Bot) for its cache/fetch helpers.
        self.discord_io: DiscordClient = BotDiscordClient(self)

    # Hook discord.py calls before the bot connects — register the cogs here.
    async def setup_hook(self) -> None:
        await self.add_cog(ModerationCog(self, self.discord_io))
        await self.add_cog(CustomCommandsCog(self, self.discord_io, self.config_cache))
        await self.add_cog(LevelingCog(self, self.discord_io))
        await self.add_cog(XpListenerCog(self, self.leveling_config_cache, self.discord_io))
        await self.add_cog(XpDecayCog(self))
        await self.add_cog(CurrencyCog(self, self.discord_io))
        await self.add_cog(BadgesCog(self, self.discord_io))
        await self.add_cog(QuestsCog(self, self.discord_io))
        await self.add_cog(PetCog(self, self.discord_io))
        await self.add_cog(KarmaCog(self, self.discord_io))
        await self.add_cog(MinigameCog(self, self.discord_io))
        await self.add_cog(RoastCog(self, self.discord_io))
        # Push the slash-command tree to Discord. The bot only sees /ban etc.
        # in clients after this sync completes.
        await self.tree.sync()
        log.info("Cogs loaded and slash commands synced.")


def build_bot() -> commands.Bot:
    bot = Rolt9Bot()

    # on_ready fires after the bot connects and Discord delivers initial state.
    # Backfill guilds — because on_guild_join only fires when the bot joins a
    # NEW guild; it does not fire for guilds the bot was already in.
    @bot.event
    async def on_ready():
        log.info("Bot ready. Connected to %d guild(s).", len(bot.guilds))
        async with session_scope() as session:
            await handle_ready([_guild_info_from(g) for g in bot.guilds], session)

    # Fires when an admin adds the bot to a new server.
    @bot.event
    async def on_guild_join(guild: discord.Guild):
        async with session_scope() as session:
            await handle_guild_join(_guild_info_from(guild), session)

    # Fires when the bot is kicked or the server is deleted.
    @bot.event
    async def on_guild_remove(guild: discord.Guild):
        async with session_scope() as session:
            await handle_guild_remove(_guild_info_from(guild), session)

    # Fires when guild metadata changes (name, icon, owner, etc.). Keeps the
    # `guilds` row in sync so dashboard views and embeds that read from the DB
    # don't show a stale server name after a rename.
    @bot.event
    async def on_guild_update(_before: discord.Guild, after: discord.Guild):
        async with session_scope() as session:
            await handle_guild_update(_guild_info_from(after), session)

    return bot
