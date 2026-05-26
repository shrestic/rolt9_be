# PermissionService — checks whether a user can manage a given guild.
#
# "Manage" means one of:
#   - The user is the owner of the guild
#   - The user has the MANAGE_GUILD bit (0x20)
#   - The user has the ADMINISTRATOR bit (0x8)
#
# Flow:
#   1. Fetch the user's guilds via DiscordOAuthClient.list_guilds_of_user(access_token)
#   2. Filter to the guilds that satisfy _can_manage()
#   3. Cache the result for CACHE_TTL_SECONDS per token so dashboard reloads
#      don't hammer the Discord API.
#
# This service uses DiscordOAuthClient (user bearer token), NOT DiscordClient
# (bot token) — Discord doesn't let a bot ask "which guilds is user X in".

import asyncio
import time
from dataclasses import dataclass

from app.discord_io.client import DiscordOAuthClient

# Permission bits per the Discord spec
# (https://discord.com/developers/docs/topics/permissions).
MANAGE_GUILD = 0x20
ADMINISTRATOR = 0x8

# Bumped from 60s → 300s because Discord rate-limits /users/@me/guilds
# aggressively (you can burn 5 requests/second). The dashboard fires multiple
# endpoints in parallel; with a 5-minute cache, most loads cost zero Discord
# calls and we stay well clear of the limit.
CACHE_TTL_SECONDS = 300


# A subset of UserGuildEntry that the BE actually cares about — drop the raw
# permissions field, keep only what FE/endpoints need.
@dataclass
class ManagedGuild:
    discord_id: int
    name: str
    icon_url: str | None


def _can_manage(owner: bool, permissions: int) -> bool:
    if owner:
        return True
    return bool(permissions & (MANAGE_GUILD | ADMINISTRATOR))


class PermissionService:
    def __init__(self, oauth: DiscordOAuthClient):
        self.oauth = oauth
        # Cache key = access_token (one entry per user). Value = (expiry_monotonic, result).
        self._cache: dict[str, tuple[float, list[ManagedGuild]]] = {}
        # Single-flight registry: when N requests cache-miss for the same token
        # at the same time (typical dashboard load: /overview + /commands +
        # /moderation + /cases all fire in parallel), only the first one fires
        # the upstream Discord call; the rest await its result. Without this,
        # 5 concurrent calls all hit Discord and trip the 429 rate limit.
        self._inflight: dict[str, asyncio.Future[list[ManagedGuild]]] = {}

    async def list_my_managed_guilds(self, access_token: str) -> list[ManagedGuild]:
        now = time.monotonic()

        # Cache hit (still within TTL) → return immediately.
        cached = self._cache.get(access_token)
        if cached and cached[0] > now:
            return cached[1]

        # Cache miss — but someone else may already be fetching for this token.
        # If so, wait for their result instead of starting a duplicate request.
        existing = self._inflight.get(access_token)
        if existing is not None:
            return await existing

        # We're the first; create the future, fetch, and broadcast the result
        # to anyone else who arrives while we're waiting on the network.
        loop = asyncio.get_event_loop()
        future: asyncio.Future[list[ManagedGuild]] = loop.create_future()
        self._inflight[access_token] = future
        try:
            raw = await self.oauth.list_guilds_of_user(access_token)
            managed = [
                ManagedGuild(discord_id=g.discord_id, name=g.name, icon_url=g.icon_url)
                for g in raw
                if _can_manage(g.owner, g.permissions)
            ]
            self._cache[access_token] = (now + CACHE_TTL_SECONDS, managed)
            future.set_result(managed)
            return managed
        except Exception as exc:
            # Propagate the failure to every waiter so they don't hang.
            future.set_exception(exc)
            raise
        finally:
            self._inflight.pop(access_token, None)

    # Convenience wrapper for the "does user manage guild X" check.
    # The require_managed_guild FastAPI dependency uses this method.
    async def user_can_manage(self, access_token: str, guild_id_str: str) -> bool:
        target = int(guild_id_str)
        for g in await self.list_my_managed_guilds(access_token):
            if g.discord_id == target:
                return True
        return False
