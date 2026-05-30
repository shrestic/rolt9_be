"""Data access for `user_quest_progress` — per quest/user/period counters.

`increment` and `try_claim` use the same atomic-guarded-UPDATE pattern as the
wallet repo: the arithmetic / claim guard lives in SQL so concurrent events
can't lose updates or double-claim. Flush only; commit at the boundary.
"""

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_quest_progress import UserQuestProgress


class QuestProgressRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(
        self, quest_id: uuid.UUID, user_id: int, period_key: str
    ) -> UserQuestProgress | None:
        r = await self.session.execute(
            select(UserQuestProgress).where(
                UserQuestProgress.quest_id == quest_id,
                UserQuestProgress.user_id == user_id,
                UserQuestProgress.period_key == period_key,
            )
        )
        return r.scalar_one_or_none()

    async def _get_or_create(
        self, quest_id: uuid.UUID, guild_id: uuid.UUID, user_id: int, period_key: str
    ) -> UserQuestProgress:
        existing = await self.get(quest_id, user_id, period_key)
        if existing is not None:
            return existing
        row = UserQuestProgress(
            quest_id=quest_id, guild_id=guild_id, user_id=user_id, period_key=period_key
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def increment(
        self,
        quest_id: uuid.UUID,
        guild_id: uuid.UUID,
        user_id: int,
        period_key: str,
        amount: int,
    ) -> None:
        """Add `amount` to this period's progress (creating the row at 0 first).

        The `progress = progress + :amount` happens in SQL, so two concurrent
        increments both apply — no lost update.
        """
        await self._get_or_create(quest_id, guild_id, user_id, period_key)
        stmt = (
            update(UserQuestProgress)
            .where(
                UserQuestProgress.quest_id == quest_id,
                UserQuestProgress.user_id == user_id,
                UserQuestProgress.period_key == period_key,
            )
            .values(progress=UserQuestProgress.progress + amount)
            .execution_options(synchronize_session="fetch")
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def try_claim(
        self, quest_id: uuid.UUID, user_id: int, period_key: str, *, target: int
    ) -> bool:
        """Atomically mark this period's quest claimed; True if it just claimed.

        The guard (`progress >= target AND claimed = false`) lives in the WHERE,
        so an incomplete quest or a double-fire matches 0 rows. Mirrors
        `WalletRepository.try_claim_daily`.
        """
        stmt = (
            update(UserQuestProgress)
            .where(
                UserQuestProgress.quest_id == quest_id,
                UserQuestProgress.user_id == user_id,
                UserQuestProgress.period_key == period_key,
                UserQuestProgress.progress >= target,
                UserQuestProgress.claimed.is_(False),
            )
            .values(claimed=True)
            .execution_options(synchronize_session="fetch")
        )
        r = await self.session.execute(stmt)
        await self.session.flush()
        return r.rowcount > 0

    async def list_for(
        self, guild_id: uuid.UUID, user_id: int, period_keys: set[str]
    ) -> dict[uuid.UUID, UserQuestProgress]:
        """Return {quest_id: progress row} for the member across the given period
        keys (the caller passes the current daily + weekly keys). At most one row
        per quest matches, since a quest has a single period."""
        r = await self.session.execute(
            select(UserQuestProgress).where(
                UserQuestProgress.guild_id == guild_id,
                UserQuestProgress.user_id == user_id,
                UserQuestProgress.period_key.in_(period_keys),
            )
        )
        return {row.quest_id: row for row in r.scalars().all()}
