# BotDiscordClient — implements DiscordClient via discord.py (lives in the bot process).
# This is one of the only 2 files in app/ allowed to `import discord` for SDK
# actions. (`discord.ext.commands` is also allowed inside cogs/ for the framework
# itself — subclassing Cog.)
#
# Unlike RestDiscordClient: the bot has a gateway cache, so get_guild/get_channel
# is O(1) RAM read. On cache miss (e.g. just-started bot that hasn't received a
# gateway event yet) we fall back to fetch_* through REST.
#
# BotDiscordClient does NOT implement DiscordOAuthClient — the bot process never
# sees user bearer tokens.

import logging
from datetime import datetime

import discord
from discord.ext import commands

from app.discord_io.client import DiscordClient
from app.discord_io.errors import (
    DiscordError,
    DiscordForbidden,
    DiscordNotFound,
)
from app.discord_io.types import (
    ChannelInfo,
    Embed,
    GuildInfo,
    RoleInfo,
    UserInfo,
)

log = logging.getLogger(__name__)


def _icon_url(guild: discord.Guild) -> str | None:
    return guild.icon.url if guild.icon else None


def _avatar_url(user: discord.abc.User) -> str | None:
    return user.avatar.url if user.avatar else None


# Convert our Embed dataclass → discord.Embed (SDK). This is the only place in
# the codebase that constructs a discord.Embed. Services and cogs only ever build
# our Embed type.
def _to_discord_embed(spec: Embed) -> discord.Embed:
    e = discord.Embed(title=spec.title, description=spec.description, color=spec.color)
    for f in spec.fields:
        e.add_field(name=f.name, value=f.value, inline=f.inline)
    if spec.footer:
        e.set_footer(text=spec.footer)
    if spec.image_url:
        e.set_image(url=spec.image_url)
    return e


class BotDiscordClient(DiscordClient):
    def __init__(self, bot: commands.Bot):
        self._bot = bot

    # ─────────────────────────────────────────────────────────────────────
    # Helpers — resolve an object from cache or fetch, normalize SDK errors
    # ─────────────────────────────────────────────────────────────────────

    # Fetch a discord.Guild: try cache first, fall back to fetch on miss.
    # Every action method starts by going through this helper.
    async def _guild(self, guild_id: int) -> discord.Guild:
        guild = self._bot.get_guild(guild_id)
        if guild is not None:
            return guild
        try:
            return await self._bot.fetch_guild(guild_id)
        except discord.NotFound as exc:
            raise DiscordNotFound(f"guild {guild_id} not found") from exc
        except discord.Forbidden as exc:
            raise DiscordForbidden(f"forbidden to fetch guild {guild_id}") from exc
        except discord.HTTPException as exc:
            raise DiscordError(str(exc)) from exc

    # Resolve a channel for sending messages. Ideally a TextChannel, but
    # bot.get_channel returns the abstract Messageable — good enough for .send().
    async def _channel(self, channel_id: int) -> discord.abc.Messageable:
        channel = self._bot.get_channel(channel_id)
        if channel is not None:
            return channel  # type: ignore[return-value]
        try:
            return await self._bot.fetch_channel(channel_id)  # type: ignore[return-value]
        except discord.NotFound as exc:
            raise DiscordNotFound(f"channel {channel_id} not found") from exc
        except discord.Forbidden as exc:
            raise DiscordForbidden(f"forbidden to fetch channel {channel_id}") from exc
        except discord.HTTPException as exc:
            raise DiscordError(str(exc)) from exc

    # Muting needs a discord.Member (not an Object) because timeout() is a method
    # on Member. Fetch if the cache doesn't have it.
    async def _member(self, guild: discord.Guild, user_id: int) -> discord.Member:
        member = guild.get_member(user_id)
        if member is not None:
            return member
        try:
            return await guild.fetch_member(user_id)
        except discord.NotFound as exc:
            raise DiscordNotFound(f"member {user_id} not in guild {guild.id}") from exc
        except discord.Forbidden as exc:
            raise DiscordForbidden(f"forbidden to fetch member {user_id}") from exc
        except discord.HTTPException as exc:
            raise DiscordError(str(exc)) from exc

    # ─────────────────────────────────────────────────────────────────────
    # Moderation actions
    # ─────────────────────────────────────────────────────────────────────

    # discord.Object(id=user_id) lets us ban/unban without fetching the User
    # first — saves a round-trip. Only mute requires a real Member object.
    async def ban_member(self, guild_id: int, user_id: int, reason: str | None) -> None:
        guild = await self._guild(guild_id)
        try:
            await guild.ban(discord.Object(id=user_id), reason=reason)
        except discord.NotFound as exc:
            raise DiscordNotFound(f"user {user_id} not found") from exc
        except discord.Forbidden as exc:
            raise DiscordForbidden(f"forbidden to ban {user_id}") from exc
        except discord.HTTPException as exc:
            raise DiscordError(str(exc)) from exc

    # Idempotent: if the user already left the guild, the kick goal is met.
    async def kick_member(self, guild_id: int, user_id: int, reason: str | None) -> None:
        guild = await self._guild(guild_id)
        try:
            await guild.kick(discord.Object(id=user_id), reason=reason)
        except discord.NotFound:
            return
        except discord.Forbidden as exc:
            raise DiscordForbidden(f"forbidden to kick {user_id}") from exc
        except discord.HTTPException as exc:
            raise DiscordError(str(exc)) from exc

    async def mute_member_until(
        self, guild_id: int, user_id: int, until: datetime, reason: str | None
    ) -> None:
        guild = await self._guild(guild_id)
        try:
            member = await self._member(guild, user_id)
        except DiscordNotFound:
            # Member left before we could apply the timeout — nothing to mute.
            return
        try:
            await member.timeout(until, reason=reason)
        except discord.Forbidden as exc:
            raise DiscordForbidden(f"forbidden to timeout {user_id}") from exc
        except discord.HTTPException as exc:
            raise DiscordError(str(exc)) from exc

    # Idempotent: a missing member can't be muted anyway, so unmute is a no-op.
    async def unmute_member(self, guild_id: int, user_id: int, reason: str | None) -> None:
        guild = await self._guild(guild_id)
        try:
            member = await self._member(guild, user_id)
        except DiscordNotFound:
            return
        try:
            # timeout(None) = clear the timeout; the member can speak again.
            await member.timeout(None, reason=reason)
        except discord.Forbidden as exc:
            raise DiscordForbidden(f"forbidden to clear timeout for {user_id}") from exc
        except discord.HTTPException as exc:
            raise DiscordError(str(exc)) from exc

    # Idempotent: swallow NotFound (already unbanned).
    async def revoke_ban(self, guild_id: int, user_id: int, reason: str | None = None) -> None:
        guild = await self._guild(guild_id)
        try:
            await guild.unban(discord.Object(id=user_id), reason=reason)
        except discord.NotFound:
            return
        except discord.Forbidden as exc:
            raise DiscordForbidden(f"forbidden to unban {user_id}") from exc
        except discord.HTTPException as exc:
            raise DiscordError(str(exc)) from exc

    # discord.py's fetch_ban returns a BanEntry if banned, or raises NotFound.
    # We translate that into a plain bool. Other failures propagate normally.
    async def is_banned(self, guild_id: int, user_id: int) -> bool:
        guild = await self._guild(guild_id)
        try:
            await guild.fetch_ban(discord.Object(id=user_id))
            return True
        except discord.NotFound:
            return False
        except discord.Forbidden as exc:
            raise DiscordForbidden(f"forbidden to read bans on guild {guild_id}") from exc
        except discord.HTTPException as exc:
            raise DiscordError(str(exc)) from exc

    # ─────────────────────────────────────────────────────────────────────
    # Reads — pure cache/fetch, no direct REST calls
    # ─────────────────────────────────────────────────────────────────────

    async def get_guild(self, guild_id: int) -> GuildInfo:
        guild = await self._guild(guild_id)
        return GuildInfo(
            discord_id=int(guild.id),
            name=guild.name,
            icon_url=_icon_url(guild),
            # member_count is gateway state — accurate only when intents.members
            # is enabled. If disabled it's 0; bot-side callers typically don't
            # care, and the FastAPI side uses RestDiscordClient.get_guild for
            # an accurate count.
            member_count=int(getattr(guild, "member_count", 0) or 0),
        )

    async def list_channels(self, guild_id: int) -> list[ChannelInfo]:
        guild = await self._guild(guild_id)
        # guild.channels covers every channel type (text/voice/category/thread).
        return [
            ChannelInfo(discord_id=int(c.id), name=c.name, type=int(c.type.value))
            for c in guild.channels
        ]

    async def list_roles(self, guild_id: int) -> list[RoleInfo]:
        guild = await self._guild(guild_id)
        return [RoleInfo(discord_id=int(r.id), name=r.name) for r in guild.roles]

    async def get_user(self, user_id: int) -> UserInfo:
        user = self._bot.get_user(user_id)
        if user is None:
            try:
                user = await self._bot.fetch_user(user_id)
            except discord.NotFound as exc:
                raise DiscordNotFound(f"user {user_id} not found") from exc
            except discord.HTTPException as exc:
                raise DiscordError(str(exc)) from exc
        return UserInfo(
            discord_id=int(user.id),
            username=str(user),
            avatar_url=_avatar_url(user),
        )

    # ─────────────────────────────────────────────────────────────────────
    # Messaging
    # ─────────────────────────────────────────────────────────────────────

    async def post_to_channel(
        self,
        channel_id: int,
        embed: Embed | None = None,
        content: str | None = None,
    ) -> None:
        channel = await self._channel(channel_id)
        kwargs: dict = {}
        if content is not None:
            kwargs["content"] = content
        if embed is not None:
            # Convert our Embed → discord.Embed right here at the boundary.
            kwargs["embed"] = _to_discord_embed(embed)
        try:
            await channel.send(**kwargs)
        except discord.Forbidden as exc:
            raise DiscordForbidden(f"forbidden to post in channel {channel_id}") from exc
        except discord.HTTPException as exc:
            raise DiscordError(str(exc)) from exc

    # DM a user about a moderation action. discord.py's user.send() handles
    # DM-channel creation internally, which is simpler than the REST adapter
    # (which has to create the channel first, then post).
    # Swallow Forbidden because a user blocking DMs is normal user privacy.
    async def notify_user_of_action(
        self,
        user_id: int,
        *,
        action: str,
        guild_name: str,
        reason: str | None,
    ) -> None:
        user = self._bot.get_user(user_id)
        if user is None:
            try:
                user = await self._bot.fetch_user(user_id)
            except discord.NotFound:
                log.info("DM target %s not found", user_id)
                return
            except discord.HTTPException:
                log.info("Could not fetch user %s for DM", user_id)
                return
        text = f"You received a **{action}** in **{guild_name}**."
        if reason:
            text += f"\nReason: {reason}"
        try:
            await user.send(text)
        except discord.Forbidden:
            log.info("User %s blocks bot DMs", user_id)
        except discord.HTTPException:
            log.info("Could not DM user %s", user_id)


__all__ = ["BotDiscordClient", "_to_discord_embed"]
