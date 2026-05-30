"""Karma facade — give peer reputation, read standings, leaderboard.

`give` validates (enabled, not self), atomically claims the per-pair 24h cooldown
(`try_grant`), then atomically increments the receiver's points — all via repos,
no sibling-service coupling. Repos flush; the caller's session scope commits.
Bot recipients are filtered at the cog layer (the service only sees user ids).
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.repositories.guild import GuildRepository
from app.repositories.karma import KarmaRepository
from app.repositories.karma_config import KarmaConfigRepository
from app.repositories.karma_grant import KarmaGrantRepository

GRANT_COOLDOWN = timedelta(hours=24)


@dataclass(frozen=True)
class GiveResult:
    receiver_points: int
    receiver_rank: int


@dataclass(frozen=True)
class KarmaStanding:
    points: int
    rank: int | None


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class KarmaService:
    def __init__(
        self,
        *,
        guild_repo: GuildRepository,
        karma_repo: KarmaRepository,
        grant_repo: KarmaGrantRepository,
        config_repo: KarmaConfigRepository,
    ):
        self.guild_repo = guild_repo
        self.karma_repo = karma_repo
        self.grant_repo = grant_repo
        self.config_repo = config_repo

    async def give(
        self, *, guild_discord_id: int, giver_id: int, receiver_id: int, now: datetime | None = None
    ) -> GiveResult:
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            raise ValueError("Server chưa đăng ký với bot.")
        cfg = await self.config_repo.get(guild.id)
        if cfg is None or not cfg.enabled:
            raise ValueError("Karma chưa được bật trên server này.")
        if giver_id == receiver_id:
            raise ValueError("Bạn không thể tự khen mình.")
        now = _as_utc(now or datetime.now(UTC))
        granted = await self.grant_repo.try_grant(
            guild.id, giver_id, receiver_id, now=now, cutoff=now - GRANT_COOLDOWN
        )
        if not granted:
            raise ValueError("Bạn đã khen người này hôm nay rồi — thử lại sau nhé.")
        points = await self.karma_repo.add_point(guild.id, receiver_id)
        rank = await self.karma_repo.rank_of(guild.id, receiver_id)
        return GiveResult(receiver_points=points, receiver_rank=rank or 1)

    async def get_standing(self, *, guild_discord_id: int, user_id: int) -> KarmaStanding:
        """Read a member's karma + rank. Never raises; unknown → (0, None)."""
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            return KarmaStanding(points=0, rank=None)
        row = await self.karma_repo.get(guild.id, user_id)
        points = row.points if row else 0
        rank = await self.karma_repo.rank_of(guild.id, user_id)
        return KarmaStanding(points=points, rank=rank)

    async def leaderboard(self, *, guild_discord_id: int, limit: int, offset: int):
        """Return (rows, total) of top-karma members for `/karma top` and REST."""
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            return [], 0
        return await self.karma_repo.leaderboard(guild.id, limit=limit, offset=offset)
