# The Protocol classes here are the contract between BE and Discord. Services /
# cogs / endpoints depend only on a Protocol, never on a concrete implementation.
#
# We split the surface into three small Protocols so each consumer depends only
# on what it actually uses:
#   - DiscordModeration  — ban/kick/mute/unmute/revoke_ban
#   - DiscordReader      — get_guild/list_channels/list_roles/get_user
#   - DiscordMessaging   — post_to_channel/notify_user_of_action
#
# DiscordClient is the union — `BotDiscordClient` implements it as a single class
# (one bot can do everything). Functions that only need a subset (e.g. delivery
# only needs DiscordMessaging) annotate the narrower type so the dependency is
# honest.
#
# DiscordOAuthClient stays separate because it's a different bounded context:
# user bearer tokens (FastAPI only), not bot tokens.
#
# Conventions:
#   - Method names express business intent (ban_member), not Discord endpoint
#     nouns (create_guild_ban).
#   - guild_id / user_id / channel_id are Discord snowflakes (int).
#   - Failures normalize to app.discord.errors (4 classes). discord.* / httpx.*
#     exceptions never leak past adapters.

from datetime import datetime
from typing import Protocol

from app.discord_io.types import (
    ChannelInfo,
    Embed,
    GuildInfo,
    OAuthTokens,
    RoleInfo,
    UserGuildEntry,
    UserInfo,
)

# ─────────────────────────────────────────────────────────────────────────────
# Outbound bot-token actions
# ─────────────────────────────────────────────────────────────────────────────


# Moderation actions that change Discord state on behalf of the bot.
class DiscordModeration(Protocol):
    async def ban_member(self, guild_id: int, user_id: int, reason: str | None) -> None: ...

    async def kick_member(self, guild_id: int, user_id: int, reason: str | None) -> None: ...

    async def mute_member_until(
        self, guild_id: int, user_id: int, until: datetime, reason: str | None
    ) -> None: ...

    async def unmute_member(self, guild_id: int, user_id: int, reason: str | None) -> None: ...

    # Idempotent — already-unbanned (404) is treated as success.
    async def revoke_ban(self, guild_id: int, user_id: int, reason: str | None = None) -> None: ...

    # True if there is an active ban entry for this user in the guild. Used by
    # /unban to skip work (and avoid logging a misleading case) when the user
    # was never banned.
    async def is_banned(self, guild_id: int, user_id: int) -> bool: ...


# Read-only queries against guilds / channels / roles / users.
class DiscordReader(Protocol):
    async def get_guild(self, guild_id: int) -> GuildInfo: ...

    async def list_channels(self, guild_id: int) -> list[ChannelInfo]: ...

    async def list_roles(self, guild_id: int) -> list[RoleInfo]: ...

    # Used by /unban where only the user_id is known.
    async def get_user(self, user_id: int) -> UserInfo: ...


# Sending messages: channel posts and direct messages to users.
class DiscordMessaging(Protocol):
    async def post_to_channel(
        self,
        channel_id: int,
        embed: Embed | None = None,
        content: str | None = None,
    ) -> None: ...

    # Send a moderation DM. The adapter builds the text and silently swallows
    # DM-blocked errors (user privacy).
    async def notify_user_of_action(
        self,
        user_id: int,
        *,
        action: str,
        guild_name: str,
        reason: str | None,
    ) -> None: ...


# The full DiscordClient is the union of the three. Concrete implementations
# (BotDiscordClient, FakeDiscordClient) implement DiscordClient and therefore
# all three sub-protocols at once.
class DiscordClient(DiscordModeration, DiscordReader, DiscordMessaging, Protocol):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# OAuth flow + user-bearer reads (FastAPI only)
# ─────────────────────────────────────────────────────────────────────────────


class DiscordOAuthClient(Protocol):
    # Exchange an authorization code for tokens. Final step of the OAuth flow.
    async def exchange_oauth_code(self, code: str) -> OAuthTokens: ...

    # Trade a refresh token for a new access token when the old one is near
    # expiry. OAuthSessionService calls this when <60s remain.
    async def refresh_oauth_token(self, refresh_token: str) -> OAuthTokens: ...

    # GET /users/@me — find out who owns the bearer token.
    async def get_user_me(self, access_token: str) -> UserInfo: ...

    # GET /users/@me/guilds — the list PermissionService filters down to
    # the guilds the user manages.
    async def list_guilds_of_user(self, access_token: str) -> list[UserGuildEntry]: ...
