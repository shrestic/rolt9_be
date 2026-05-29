"""Data access for `user_badge` — earned achievement badges.

Insert-only (badges are permanent): `add` is idempotent via the unique
constraint, `earned_keys` powers the evaluator's "already held" check, and
`list_earned` backs the `/badges` display. Flush only — the caller's
session scope owns the commit (Unit-of-Work).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_badge import UserBadge


class BadgeRepository:
    def __init__(self, session: AsyncSession):
        # Shared session injected by FastAPI's `get_db` dependency — all methods
        # participate in the same Unit-of-Work transaction.
        self.session = session

    async def earned_keys(self, guild_id: uuid.UUID, user_id: int) -> set[str]:
        """Return the set of badge keys this member already holds.

        Used by the badge evaluator before every award attempt: comparing this
        set against the candidate keys means we never even try to insert a
        duplicate, which avoids noisy IntegrityErrors on the happy path.
        """
        r = await self.session.execute(
            select(UserBadge.badge_key).where(
                UserBadge.guild_id == guild_id, UserBadge.user_id == user_id
            )
        )
        return set(r.scalars().all())

    async def add(self, guild_id: uuid.UUID, user_id: int, badge_key: str) -> bool:
        """Award a badge. Returns True if newly added, False if already held.

        Idempotent: we check first, then insert. The unique constraint
        (`uq_user_badge`) is the ultimate guard, but checking avoids a noisy
        IntegrityError on the common "already have it" path. The check-then-insert
        is safe within a single async session because there is no concurrent
        writer for the same (guild_id, user_id, badge_key) triple inside one
        request's transaction.
        """
        # Check whether the badge row already exists for this member.
        existing = await self.session.execute(
            select(UserBadge.id).where(
                UserBadge.guild_id == guild_id,
                UserBadge.user_id == user_id,
                UserBadge.badge_key == badge_key,
            )
        )
        if existing.scalar_one_or_none() is not None:
            # Already earned — nothing to do.
            return False

        # New badge — insert and flush so the row gets a real PK within this
        # transaction (no commit yet; the caller's session_scope does that).
        self.session.add(UserBadge(guild_id=guild_id, user_id=user_id, badge_key=badge_key))
        await self.session.flush()
        return True

    async def list_earned(self, guild_id: uuid.UUID, user_id: int) -> list[UserBadge]:
        """Return the member's earned badge rows, oldest first (for display).

        `earned_at ASC` gives a stable chronological order so the `/badges`
        embed always shows badges in the order they were unlocked.
        """
        r = await self.session.execute(
            select(UserBadge)
            .where(UserBadge.guild_id == guild_id, UserBadge.user_id == user_id)
            .order_by(UserBadge.earned_at.asc())
        )
        return list(r.scalars().all())
