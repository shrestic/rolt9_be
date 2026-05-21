import time
from dataclasses import dataclass

from app.services.discord_api import DiscordAPIClient

MANAGE_GUILD = 0x20
ADMINISTRATOR = 0x8
CACHE_TTL_SECONDS = 60


@dataclass
class ManagedGuild:
    discord_id: int
    name: str
    icon_url: str | None


def _can_manage(g: dict) -> bool:
    if g.get("owner") is True:
        return True
    try:
        perms = int(g.get("permissions", "0"))
    except (TypeError, ValueError):
        return False
    return bool(perms & (MANAGE_GUILD | ADMINISTRATOR))


class PermissionService:
    def __init__(self, api: DiscordAPIClient | None = None):
        self.api = api or DiscordAPIClient()
        # cache keyed by access_token → (expires_at_monotonic, list[ManagedGuild])
        self._cache: dict[str, tuple[float, list[ManagedGuild]]] = {}

    async def list_my_managed_guilds(self, access_token: str) -> list[ManagedGuild]:
        now = time.monotonic()
        cached = self._cache.get(access_token)
        if cached and cached[0] > now:
            return cached[1]

        raw = await self.api.list_user_guilds(access_token)
        managed = []
        for g in raw:
            if not _can_manage(g):
                continue
            icon = (
                f"https://cdn.discordapp.com/icons/{g['id']}/{g['icon']}.png"
                if g.get("icon")
                else None
            )
            managed.append(ManagedGuild(discord_id=int(g["id"]), name=g["name"], icon_url=icon))
        self._cache[access_token] = (now + CACHE_TTL_SECONDS, managed)
        return managed

    async def user_can_manage(self, access_token: str, guild_id_str: str) -> bool:
        target = int(guild_id_str)
        for g in await self.list_my_managed_guilds(access_token):
            if g.discord_id == target:
                return True
        return False
