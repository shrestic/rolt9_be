# Fake implementations of DiscordClient + DiscordOAuthClient for unit tests.
# Pure in-memory — no httpx or discord.py calls. They record every call so
# tests can assert "the service invoked which method with which args".
#
# Typical usage:
#   discord = FakeDiscordClient()
#   service = ModerationService(session, discord, repos...)
#   await service.ban(guild_id=55, target=Actor(7, "x"), ...)
#   assert (55, 7) in discord.bans
#   assert len(discord.posted_messages) == 1   # mod-log post

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.discord_io.errors import DiscordError, DiscordNotFound
from app.discord_io.types import (
    ChannelInfo,
    Embed,
    GuildInfo,
    OAuthTokens,
    RoleInfo,
    UserGuildEntry,
    UserInfo,
)


@dataclass
class FakeDiscordClient:
    # State recorded per action — tests assert against these collections.
    bans: set[tuple[int, int]] = field(default_factory=set)
    kicks: list[tuple[int, int, str | None]] = field(default_factory=list)
    mutes: list[tuple[int, int, datetime, str | None]] = field(default_factory=list)
    unmutes: list[tuple[int, int, str | None]] = field(default_factory=list)
    posted_messages: list[tuple[int, Embed | None, str | None]] = field(default_factory=list)
    dms_sent: list[dict[str, Any]] = field(default_factory=list)

    # Inject exception classes to test failure paths (e.g. bot can't send a DM).
    raise_on_revoke: type[DiscordError] | None = None
    raise_on_post: type[DiscordError] | None = None
    raise_on_dm: type[DiscordError] | None = None

    # Lookup tables for read methods.
    users: dict[int, UserInfo] = field(default_factory=dict)
    guilds: dict[int, GuildInfo] = field(default_factory=dict)
    channels: dict[int, list[ChannelInfo]] = field(default_factory=dict)
    roles: dict[int, list[RoleInfo]] = field(default_factory=dict)

    async def ban_member(self, guild_id: int, user_id: int, reason: str | None) -> None:
        self.bans.add((guild_id, user_id))

    async def kick_member(self, guild_id: int, user_id: int, reason: str | None) -> None:
        self.kicks.append((guild_id, user_id, reason))

    async def mute_member_until(
        self, guild_id: int, user_id: int, until: datetime, reason: str | None
    ) -> None:
        self.mutes.append((guild_id, user_id, until, reason))

    async def unmute_member(self, guild_id: int, user_id: int, reason: str | None) -> None:
        self.unmutes.append((guild_id, user_id, reason))

    async def revoke_ban(self, guild_id: int, user_id: int, reason: str | None = None) -> None:
        if self.raise_on_revoke is not None:
            raise self.raise_on_revoke("simulated")
        # Idempotent — discard, never raise if it's not there.
        self.bans.discard((guild_id, user_id))

    async def is_banned(self, guild_id: int, user_id: int) -> bool:
        return (guild_id, user_id) in self.bans

    async def get_guild(self, guild_id: int) -> GuildInfo:
        info = self.guilds.get(guild_id)
        if info is None:
            raise DiscordNotFound(f"guild {guild_id}")
        return info

    async def list_channels(self, guild_id: int) -> list[ChannelInfo]:
        return self.channels.get(guild_id, [])

    async def list_roles(self, guild_id: int) -> list[RoleInfo]:
        return self.roles.get(guild_id, [])

    async def get_user(self, user_id: int) -> UserInfo:
        info = self.users.get(user_id)
        if info is None:
            raise DiscordNotFound(f"user {user_id}")
        return info

    async def post_to_channel(
        self,
        channel_id: int,
        embed: Embed | None = None,
        content: str | None = None,
    ) -> None:
        if self.raise_on_post is not None:
            raise self.raise_on_post("simulated")
        self.posted_messages.append((channel_id, embed, content))

    async def notify_user_of_action(
        self,
        user_id: int,
        *,
        action: str,
        guild_name: str,
        reason: str | None,
    ) -> None:
        if self.raise_on_dm is not None:
            raise self.raise_on_dm("simulated")
        self.dms_sent.append(
            {
                "user_id": user_id,
                "action": action,
                "guild_name": guild_name,
                "reason": reason,
            }
        )


@dataclass
class FakeOAuthClient:
    # Lookup tables: token-or-code → (UserInfo / OAuthTokens / list).
    # If a test doesn't set them, the methods return sensible defaults
    # (see the method bodies).
    exchanged: dict[str, OAuthTokens] = field(default_factory=dict)
    refreshed: dict[str, OAuthTokens] = field(default_factory=dict)
    users_by_token: dict[str, UserInfo] = field(default_factory=dict)
    guilds_by_token: dict[str, list[UserGuildEntry]] = field(default_factory=dict)

    # Counters so tests can assert "the service called this N times".
    refresh_calls: int = 0
    list_guilds_calls: int = 0

    async def exchange_oauth_code(self, code: str) -> OAuthTokens:
        tokens = self.exchanged.get(code)
        if tokens is None:
            # Default — return an "AT-{code}" token so tests get a predictable value.
            tokens = OAuthTokens(
                access_token=f"AT-{code}",
                refresh_token=f"RT-{code}",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                scope="identify guilds",
            )
        return tokens

    async def refresh_oauth_token(self, refresh_token: str) -> OAuthTokens:
        self.refresh_calls += 1
        tokens = self.refreshed.get(refresh_token)
        if tokens is None:
            tokens = OAuthTokens(
                access_token="NEW",
                refresh_token="RT-NEW",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                scope="identify guilds",
            )
        return tokens

    async def get_user_me(self, access_token: str) -> UserInfo:
        info = self.users_by_token.get(access_token)
        if info is None:
            return UserInfo(discord_id=1, username="testuser", avatar_url=None)
        return info

    async def list_guilds_of_user(self, access_token: str) -> list[UserGuildEntry]:
        self.list_guilds_calls += 1
        return self.guilds_by_token.get(access_token, [])
