"""Paginated leaderboard view over the `user_xp` table.

Wraps `UserXpRepository.leaderboard()` and decorates each row with its
computed level (the DB only stores cumulative XP; level is derived).
Both the HTTP API (`GET /leveling/leaderboard`) and the Discord slash
command (`/leaderboard`) hit this service so they always agree on shape,
ordering, and pagination math.

Rank assignment is **offset-based** rather than per-row: we trust the SQL
`ORDER BY total_xp DESC, user_id ASC` from the repo and number the rows
within the page starting at `offset + 1`. That's correct for non-tied
scores; ties get tiebroken stably by `user_id`. We deliberately don't
implement "dense rank" (where ties share a rank) because the dashboard
shows a 1-indexed list and the cost of running window functions
(`RANK() OVER ...`) on every leaderboard query isn't worth it.
"""

import uuid
from dataclasses import dataclass

from app.repositories.user_xp import UserXpRepository
from app.services.leveling.xp_calculator import level_for_xp


@dataclass(frozen=True)
class LeaderboardEntry:
    """One row of the leaderboard, ready to render.

    `rank` is already resolved (1-indexed) — callers do not need to
    compute positions themselves.

    Attributes:
        rank: 1-indexed position in the *full* leaderboard, not just this
            page. So page 2 with page_size 20 starts at rank 21.
        user_id: Discord snowflake of the member.
        total_xp: Cumulative XP they've earned in this guild.
        level: Derived from `total_xp` via `level_for_xp`. Stored on the
            entry so renderers don't need to import the calculator.
    """

    rank: int
    user_id: int
    total_xp: int
    level: int


@dataclass(frozen=True)
class LeaderboardPage:
    """One page of the leaderboard plus the total count for pagination UI.

    Attributes:
        items: The entries for this page, ordered by `rank` ascending
            (i.e. highest XP first within the page).
        total: Total number of `user_xp` rows in the guild. Used by the
            client to render "page N of M" / "showing X-Y of Z".
    """

    items: list[LeaderboardEntry]
    total: int


class LeaderboardService:
    """Read-only service that builds a `LeaderboardPage`.

    Holds only a `UserXpRepository` — no Discord I/O, no caches. Cheap to
    instantiate per request (which is how the DI factory uses it).
    """

    def __init__(self, xp_repo: UserXpRepository):
        """Store the repo dependency.

        Args:
            xp_repo: Repository scoped to the same SQLAlchemy session as
                everything else in this request / event loop iteration.
        """
        self.xp_repo = xp_repo

    async def top(
        self, guild_id: uuid.UUID, *, limit: int = 20, offset: int = 0
    ) -> LeaderboardPage:
        """Return one page of the leaderboard for `guild_id`.

        Rank is computed from the `offset` parameter (DB orders rows by
        `total_xp DESC, user_id ASC`), so we don't pay an extra
        `COUNT(*) WHERE total_xp > ?` per row — the price of a leaderboard
        query stays O(limit) regardless of how deep into the list you page.

        Args:
            guild_id: Internal UUID of the guild (not the Discord snowflake).
                Resolve the snowflake via `GuildRepository.get_by_discord_id`
                before calling this.
            limit: Page size, capped by the HTTP schema at 100. Discord
                slash command uses 10.
            offset: How many rows to skip. `(page - 1) * page_size`.

        Returns:
            A `LeaderboardPage` with `items` ordered by descending XP and
            `total` set to the guild-wide row count. If the guild has no
            XP rows at all, `items` is empty and `total` is 0.

        Example:
            >>> page = await service.top(gid, limit=20, offset=0)
            >>> page.items[0].rank
            1
            >>> page.items[0].total_xp  # Highest in the guild
            123456
            >>> page.total              # All members with any XP
            42
        """
        rows, total = await self.xp_repo.leaderboard(guild_id, limit=limit, offset=offset)

        # Decorate each row with a 1-indexed rank (= offset + position in
        # this page) and the level computed from cumulative XP.
        items = [
            LeaderboardEntry(
                rank=offset + idx + 1,
                user_id=row.user_id,
                total_xp=row.total_xp,
                level=level_for_xp(row.total_xp),
            )
            for idx, row in enumerate(rows)
        ]
        return LeaderboardPage(items=items, total=total)
