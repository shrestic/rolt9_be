# Cog for legacy-style prefix custom commands ("!"). Different from slash commands:
#   - Slash command (ModerationCog): the bot registers commands with Discord;
#                                    users type "/"
#   - Custom command (CustomCommandsCog): the bot intercepts on_message and
#                                          matches a prefix + trigger
#
# Admins define custom commands in the dashboard (stored in the DB). The cog
# reads them through GuildConfigCache to avoid hitting the DB for every message.

import time

import discord
from discord.ext import commands

from app.bot.cache.guild_config_cache import GuildConfig
from app.discord_io.client import DiscordClient
from app.services.custom_command_service import (
    build_context,
    is_allowed,
    is_on_cooldown,
    render_embed_spec,
    render_template,
)


# Wrap a discord.Message into the context dict the shared renderer expects.
# All actual placeholder logic lives in `build_context` so the dashboard
# preview uses identical substitutions.
def _build_context_from_message(message: discord.Message) -> dict:
    guild = message.guild
    author = message.author
    return build_context(
        user_display=getattr(author, "display_name", str(author)),
        user_mention=author.mention,
        server_name=guild.name,
        member_count=int(getattr(guild, "member_count", 0) or 0),
    )


# Core handler — pulled out of the Cog so it's easy to test (no discord.py
# runtime required). Pure logic + a single side effect (calls
# discord_io.post_to_channel).
async def handle_message(
    message: discord.Message,
    discord_io: DiscordClient,
    config: GuildConfig | None,
    cooldowns: dict,
    now: float | None = None,
) -> bool:
    now = time.monotonic() if now is None else now

    # No config for this guild or admin disabled the feature → ignore.
    if config is None or not config.enabled:
        return False

    # Prefix check.
    content = message.content or ""
    if not content.startswith(config.prefix):
        return False

    # Extract trigger (the first word after the prefix).
    trigger = content[len(config.prefix) :].split(" ", 1)[0].lower()
    if not trigger:
        return False

    # Find the matching command.
    cmd = next((c for c in config.commands if c.trigger == trigger), None)
    if cmd is None:
        return False

    # Role + channel restrictions.
    member_role_ids = [r.id for r in getattr(message.author, "roles", [])]
    if not is_allowed(
        member_role_ids=member_role_ids,
        channel_id=int(message.channel.id),
        allowed_role_ids=cmd.allowed_role_ids,
        allowed_channel_ids=cmd.allowed_channel_ids,
    ):
        return False

    # Cooldown — keyed on (guild, command, user) so cooldown is per-user-per-command.
    key = (int(message.guild.id), cmd.id, int(message.author.id))
    if is_on_cooldown(last_used=cooldowns.get(key), cooldown_seconds=cmd.cooldown_seconds, now=now):
        return False
    cooldowns[key] = now

    # Render and post.
    context = _build_context_from_message(message)
    if cmd.response_type == "embed" and cmd.embed:
        await discord_io.post_to_channel(
            int(message.channel.id), embed=render_embed_spec(cmd.embed, context)
        )
    else:
        await discord_io.post_to_channel(
            int(message.channel.id), content=render_template(cmd.response_text or "", context)
        )
    return True


class CustomCommandsCog(commands.Cog):
    def __init__(self, bot: commands.Bot, discord_io: DiscordClient, cache):
        self.bot = bot
        self.discord_io = discord_io
        self.cache = cache
        # Cooldown state lives in the bot process. It resets on bot restart.
        self._cooldowns: dict = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        # Ignore other bots and DMs (custom commands only run inside guilds).
        if message.author.bot or message.guild is None:
            return
        # Fetch config from cache (loads from DB on miss).
        config = await self.cache.get(int(message.guild.id))
        await handle_message(message, self.discord_io, config, self._cooldowns)
