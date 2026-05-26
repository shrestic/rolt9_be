import time
from dataclasses import dataclass

from app.db.session import AsyncSessionLocal
from app.repositories.custom_command import CustomCommandRepository
from app.repositories.guild import GuildRepository
from app.repositories.guild_settings import GuildSettingsRepository

DEFAULT_TTL = 45


@dataclass
class CachedCommand:
    id: str
    trigger: str
    response_type: str
    response_text: str | None
    embed: dict | None
    allowed_role_ids: list[int]
    allowed_channel_ids: list[int]
    cooldown_seconds: int


@dataclass
class GuildConfig:
    prefix: str
    enabled: bool
    commands: list[CachedCommand]
    moderation: dict


class GuildConfigCache:
    def __init__(self, session_factory=AsyncSessionLocal, ttl: int = DEFAULT_TTL):
        self._factory = session_factory
        self._ttl = ttl
        self._cache: dict[int, tuple[float, GuildConfig | None]] = {}

    async def get(self, guild_discord_id: int) -> GuildConfig | None:
        now = time.monotonic()
        cached = self._cache.get(guild_discord_id)
        if cached and cached[0] > now:
            return cached[1]
        cfg = await self._load(guild_discord_id)
        self._cache[guild_discord_id] = (now + self._ttl, cfg)
        return cfg

    def invalidate(self, guild_discord_id: int) -> None:
        self._cache.pop(guild_discord_id, None)

    async def _load(self, guild_discord_id: int) -> GuildConfig | None:
        async with self._factory() as session:
            guild = await GuildRepository(session).get_by_discord_id(guild_discord_id)
            if guild is None:
                return None
            gs = await GuildSettingsRepository(session).get(guild.id)
            raw = await CustomCommandRepository(session).list_by_guild(guild.id, enabled_only=True)
            commands = [
                CachedCommand(
                    id=str(c.id),
                    trigger=c.trigger,
                    response_type=c.response_type,
                    response_text=c.response_text,
                    embed=c.embed,
                    allowed_role_ids=[int(x) for x in (c.allowed_role_ids or [])],
                    allowed_channel_ids=[int(x) for x in (c.allowed_channel_ids or [])],
                    cooldown_seconds=c.cooldown_seconds,
                )
                for c in raw
            ]
            cmd_settings = (gs.commands if gs else {}) or {}
            return GuildConfig(
                prefix=cmd_settings.get("prefix", "!"),
                enabled=cmd_settings.get("enabled", True),
                commands=commands,
                moderation=(gs.moderation if gs else {}) or {},
            )
