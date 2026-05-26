# Thin domain types for Discord — frozen dataclasses, no dependency on
# discord.py or httpx. These are the only types allowed to cross the
# DiscordClient / DiscordOAuthClient boundary. Adapters convert from
# discord.Member / httpx JSON into these types.

from dataclasses import dataclass, field
from datetime import datetime


# One field in an embed (a single key-value row, may sit inline with siblings).
@dataclass(frozen=True)
class EmbedField:
    name: str
    value: str
    inline: bool = False


# Embed = the rich "card" the bot posts into a channel. A pure dataclass —
# adapters render it into discord.Embed (bot side) or a JSON dict (REST side).
@dataclass(frozen=True)
class Embed:
    title: str | None = None
    description: str | None = None
    color: int = 0x5865F2  # Discord blurple — default color
    fields: list[EmbedField] = field(default_factory=list)
    footer: str | None = None
    image_url: str | None = None


# Basic info about a guild (server). member_count is approximate when fetched
# from REST with with_counts=true.
@dataclass(frozen=True)
class GuildInfo:
    discord_id: int
    name: str
    icon_url: str | None
    member_count: int = 0


# One channel inside a guild. `type` is Discord's channel type enum
# (0=text, 2=voice, 4=category, ...).
@dataclass(frozen=True)
class ChannelInfo:
    discord_id: int
    name: str
    type: int


# One role inside a guild.
@dataclass(frozen=True)
class RoleInfo:
    discord_id: int
    name: str


# A Discord user, not tied to a specific guild.
@dataclass(frozen=True)
class UserInfo:
    discord_id: int
    username: str
    avatar_url: str | None


# One entry from "the user's list of guilds" (fetched with user bearer token).
# `permissions` is Discord's raw bitfield — PermissionService decodes it to
# check for MANAGE_GUILD / ADMINISTRATOR.
@dataclass(frozen=True)
class UserGuildEntry:
    discord_id: int
    name: str
    icon_url: str | None
    owner: bool
    permissions: int


# Tokens returned after exchanging an OAuth code or refreshing.
@dataclass(frozen=True)
class OAuthTokens:
    access_token: str
    refresh_token: str
    expires_at: datetime
    scope: str
