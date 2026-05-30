"""Data access for `karma_grant` — the per giver→receiver cooldown ledger.

`try_grant` mirrors `WalletRepository.try_claim_daily`: an atomic guarded UPDATE
whose WHERE holds the cooldown predicate, so two near-simultaneous grants for the
same pair can't both pass. Flush only; commit at the boundary.
"""

import uuid
from datetime import datetime

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.karma_grant import KarmaGrant


class KarmaGrantRepository:
    def __init__(self, session: AsyncSession):
        # Shared async session; all methods join the same Unit-of-Work transaction.
        self.session = session

    async def _get_or_create(
        self, guild_id: uuid.UUID, giver_id: int, receiver_id: int
    ) -> KarmaGrant:
        """Return the grant ledger row, inserting a seed row (last_granted_at=NULL) on first access.

        Private helper: ensures a row exists so the guarded UPDATE in `try_grant`
        always has something to match. Without it, a first-ever grant would match
        0 rows and silently fail.
        """
        r = await self.session.execute(
            select(KarmaGrant).where(
                KarmaGrant.guild_id == guild_id,
                KarmaGrant.giver_id == giver_id,
                KarmaGrant.receiver_id == receiver_id,
            )
        )
        row = r.scalar_one_or_none()
        if row is not None:
            return row
        # First time this giver→receiver pair interacts; seed with NULL timestamp.
        row = KarmaGrant(guild_id=guild_id, giver_id=giver_id, receiver_id=receiver_id)
        self.session.add(row)
        await self.session.flush()
        return row

    async def try_grant(
        self,
        guild_id: uuid.UUID,
        giver_id: int,
        receiver_id: int,
        *,
        now: datetime,
        cutoff: datetime,
    ) -> bool:
        """Atomically claim a grant slot for this pair; True if allowed.

        Eligible iff this giver never granted this receiver, or the last grant is
        older than `cutoff`. The guard lives in the WHERE so a double-fire can't
        bypass it:

            WHERE last_granted_at IS NULL OR last_granted_at <= cutoff

        Two simultaneous `/karma give` commands for the same pair reach this UPDATE
        concurrently; only one can match the WHERE (the DB serialises the UPDATE
        page lock), and the loser sees rowcount=0 → False.

        Args:
            now: Timestamp to write into `last_granted_at` on success.
            cutoff: Eligibility boundary — any last_granted_at at or before this
                    value means the cooldown has expired. Computed by the caller
                    (e.g. `now - timedelta(hours=24)`) so tests can inject
                    deterministic times without touching the clock.
        """
        await self._get_or_create(guild_id, giver_id, receiver_id)
        stmt = (
            update(KarmaGrant)
            .where(
                KarmaGrant.guild_id == guild_id,
                KarmaGrant.giver_id == giver_id,
                KarmaGrant.receiver_id == receiver_id,
                # The cooldown guard — this is what makes the operation atomic.
                # NULL means never granted (always eligible); a timestamp at or
                # before cutoff means the cooldown window has lapsed.
                or_(KarmaGrant.last_granted_at.is_(None), KarmaGrant.last_granted_at <= cutoff),
            )
            .values(last_granted_at=now)
            # "fetch" strategy: re-select from DB instead of evaluating WHERE in
            # Python. Required so SQLite/test sessions survive tz-aware comparisons.
            .execution_options(synchronize_session="fetch")
        )
        r = await self.session.execute(stmt)
        await self.session.flush()
        # rowcount 1 → cooldown passed and timestamp stamped; 0 → still on cooldown.
        return r.rowcount > 0
