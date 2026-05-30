"""Data access for `user_karma` — received reputation points + leaderboard.

`add_point` mirrors the wallet's atomic increment (SQL `points = points + 1` so
concurrent grants don't lose updates). `leaderboard`/`rank_of` mirror the wallet
leaderboard, backed by the `(guild_id, points)` index. Flush only; commit at the
boundary.
"""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_karma import UserKarma


class KarmaRepository:
    def __init__(self, session: AsyncSession):
        # Shared async session; all methods join the same Unit-of-Work transaction.
        self.session = session

    async def get(self, guild_id: uuid.UUID, user_id: int) -> UserKarma | None:
        """Return the karma row for this member, or None if they have no karma yet."""
        r = await self.session.execute(
            select(UserKarma).where(UserKarma.guild_id == guild_id, UserKarma.user_id == user_id)
        )
        return r.scalar_one_or_none()

    async def _get_or_create(self, guild_id: uuid.UUID, user_id: int) -> UserKarma:
        """Return the karma row, inserting a zero-points seed row on first access.

        Private helper used by `add_point` to guarantee a row exists before
        the guarded UPDATE fires; without it the UPDATE would match 0 rows on
        the very first grant.
        """
        existing = await self.get(guild_id, user_id)
        if existing is not None:
            return existing
        # Lazily create the row with 0 points; the following UPDATE will bring it to 1.
        row = UserKarma(guild_id=guild_id, user_id=user_id, points=0)
        self.session.add(row)
        await self.session.flush()
        return row

    async def add_point(self, guild_id: uuid.UUID, user_id: int) -> int:
        """Add 1 karma to the member; return the new total. Atomic increment.

        Uses SQL `points = points + 1` inside a single UPDATE so two near-simultaneous
        awards for the same member never lose each other (no read-modify-write gap).
        `synchronize_session="fetch"` tells SQLAlchemy to re-select the row from
        the DB when refreshing the identity map, which is required on SQLite/tests
        where the default "evaluate" strategy can trip over timezone mismatches.
        """
        await self._get_or_create(guild_id, user_id)
        stmt = (
            update(UserKarma)
            .where(UserKarma.guild_id == guild_id, UserKarma.user_id == user_id)
            .values(points=UserKarma.points + 1)
            .execution_options(synchronize_session="fetch")
        )
        await self.session.execute(stmt)
        await self.session.flush()
        # Re-fetch so the returned int reflects the DB value, not a Python estimate.
        row = await self.get(guild_id, user_id)
        return row.points

    async def leaderboard(
        self, guild_id: uuid.UUID, *, limit: int = 10, offset: int = 0
    ) -> tuple[list[UserKarma], int]:
        """One page of the highest-karma members + total count (points DESC).

        A separate COUNT query gives the total without fetching all rows, which
        keeps memory low even for large guilds. Tie-break by `user_id ASC` for
        stable pagination.
        """
        total_r = await self.session.execute(
            select(func.count()).select_from(UserKarma).where(UserKarma.guild_id == guild_id)
        )
        total = int(total_r.scalar_one())
        r = await self.session.execute(
            select(UserKarma)
            .where(UserKarma.guild_id == guild_id)
            .order_by(UserKarma.points.desc(), UserKarma.user_id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(r.scalars().all()), total

    async def rank_of(self, guild_id: uuid.UUID, user_id: int) -> int | None:
        """1-indexed rank by points, or None if the member has no karma row.

        Rank = (members with strictly more points) + 1. Backed by the
        `(guild_id, points)` index, so it's a fast index scan rather than a
        full table scan.
        """
        target = await self.get(guild_id, user_id)
        if target is None:
            return None
        r = await self.session.execute(
            select(func.count())
            .select_from(UserKarma)
            .where(UserKarma.guild_id == guild_id, UserKarma.points > target.points)
        )
        return int(r.scalar_one()) + 1
