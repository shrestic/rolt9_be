# In-memory cache of GuildLevelingConfig keyed by Discord snowflake. The
# xp_listener consults this for every message, so the cache exists to avoid
# turning every chat message into a DB round-trip.
#
# TTL is short (45s) so stale settings auto-correct even if an admin forgets
# to push a settings update through the dashboard. The PUT-settings endpoint
# also invalidates explicitly via Bot.leveling_config_cache.invalidate(...).
#
# The cache is bounded by CACHE_SIZE entries with LRU eviction so a bot that
# joins many guilds can't accumulate stale entries forever (TTL expires the
# *value* but the *key* would otherwise sit in the dict until the next
# `get(key)` call). Eviction is best-effort: the evicted guild just pays a
# DB round-trip on its next message, no correctness impact.

import time
from collections import OrderedDict
from dataclasses import dataclass

from app.core.enums import LevelRoleMode, NotificationMode
from app.db.session import AsyncSessionLocal
from app.repositories.guild import GuildRepository
from app.repositories.leveling_config import GuildLevelingConfigRepository

DEFAULT_TTL = 45
# Max number of guild entries held in memory. ~10k covers any realistic
# production fleet; an evicted guild just re-loads from DB next message.
CACHE_SIZE = 10_000


@dataclass
class CachedLevelingConfig:
    enabled: bool
    xp_min: int
    xp_max: int
    cooldown_seconds: int
    min_message_length: int
    ignore_emoji_only: bool
    ignore_link_only: bool
    ignored_channel_ids: list[int]
    ignored_role_ids: list[int]
    notification_mode: NotificationMode
    notification_channel_id: int | None
    level_role_mode: LevelRoleMode


class LevelingConfigCache:
    def __init__(
        self,
        session_factory=AsyncSessionLocal,
        ttl: int = DEFAULT_TTL,
        max_size: int = CACHE_SIZE,
    ):
        self._factory = session_factory
        self._ttl = ttl
        self._max_size = max_size
        # OrderedDict makes LRU eviction a one-liner: `popitem(last=False)`
        # removes the oldest entry; `move_to_end(key)` marks "just used".
        self._cache: OrderedDict[int, tuple[float, CachedLevelingConfig | None]] = OrderedDict()

    async def get(self, guild_discord_id: int) -> CachedLevelingConfig | None:
        now = time.monotonic()
        cached = self._cache.get(guild_discord_id)
        if cached and cached[0] > now:
            # Cache hit on a still-fresh entry — bump to MRU end so it
            # survives future evictions over genuinely cold keys.
            self._cache.move_to_end(guild_discord_id)
            return cached[1]
        # Either miss or expired entry → reload from DB.
        cfg = await self._load(guild_discord_id)
        self._cache[guild_discord_id] = (now + self._ttl, cfg)
        # Bump existing key to MRU end (no-op on fresh insert; move on refresh).
        self._cache.move_to_end(guild_discord_id)
        # Evict oldest if we just blew past the cap.
        if len(self._cache) > self._max_size:
            self._cache.popitem(last=False)
        return cfg

    def invalidate(self, guild_discord_id: int) -> None:
        self._cache.pop(guild_discord_id, None)

    async def _load(self, guild_discord_id: int) -> CachedLevelingConfig | None:
        async with self._factory() as session:
            guild = await GuildRepository(session).get_by_discord_id(guild_discord_id)
            if guild is None:
                return None
            cfg = await GuildLevelingConfigRepository(session).get(guild.id)
            if cfg is None:
                return None
            return CachedLevelingConfig(
                enabled=cfg.enabled,
                xp_min=cfg.xp_min,
                xp_max=cfg.xp_max,
                cooldown_seconds=cfg.cooldown_seconds,
                min_message_length=cfg.min_message_length,
                ignore_emoji_only=cfg.ignore_emoji_only,
                ignore_link_only=cfg.ignore_link_only,
                ignored_channel_ids=[int(x) for x in (cfg.ignored_channel_ids or [])],
                ignored_role_ids=[int(x) for x in (cfg.ignored_role_ids or [])],
                notification_mode=cfg.notification_mode,
                notification_channel_id=(
                    int(cfg.notification_channel_id)
                    if cfg.notification_channel_id is not None
                    else None
                ),
                level_role_mode=cfg.level_role_mode,
            )
