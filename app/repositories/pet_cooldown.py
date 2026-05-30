"""Data access for `user_pet_cooldown` — the `/pet play` per-user cooldown.

`try_play` mirrors `WalletRepository.try_claim_daily`: an atomic guarded UPDATE
whose WHERE holds the cooldown predicate, so two near-simultaneous plays can't
both pass. Flush only; commit at the boundary.
"""

import uuid
from datetime import datetime

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_pet_cooldown import UserPetCooldown


class PetCooldownRepository:
    def __init__(self, session: AsyncSession):
        # Holds the async session injected by FastAPI's `get_db` dependency.
        # Shared across all methods so they participate in the same Unit-of-Work.
        self.session = session

    async def _get_or_create(self, guild_id: uuid.UUID, user_id: int) -> UserPetCooldown:
        """Ensure a cooldown row exists for (guild_id, user_id), creating if absent.

        Private helper called by `try_play` before the guarded UPDATE so the
        WHERE always has a row to match. `last_play_at` starts NULL (never played),
        which the UPDATE's eligibility predicate treats as always-eligible.
        """
        r = await self.session.execute(
            select(UserPetCooldown).where(
                UserPetCooldown.guild_id == guild_id, UserPetCooldown.user_id == user_id
            )
        )
        row = r.scalar_one_or_none()
        if row is not None:
            return row

        # First play ever for this (guild, member) — create the cooldown sentinel.
        row = UserPetCooldown(guild_id=guild_id, user_id=user_id)
        self.session.add(row)
        await self.session.flush()
        return row

    async def try_play(
        self, guild_id: uuid.UUID, user_id: int, *, now: datetime, cutoff: datetime
    ) -> bool:
        """Atomically claim a play slot; True if allowed, False if on cooldown.

        Eligible iff never played (last_play_at IS NULL) or the last play is at
        or before `cutoff`. The eligibility guard lives entirely in the WHERE
        clause, so two near-simultaneous `/pet play` commands can't both pass —
        only one UPDATE matches, the other reports rowcount=0 (on cooldown).

        This is the same race-safety pattern as `WalletRepository.try_claim_daily`:
        read-then-write would leave a TOCTOU window; a single guarded UPDATE closes
        it atomically.

        Args:
            guild_id: The guild where the play is happening.
            user_id:  Discord snowflake of the member attempting to play.
            now:      Timestamp to stamp into `last_play_at` on success.
            cutoff:   Eligibility boundary computed by the caller (now - cooldown).
                      A play is eligible only if `last_play_at <= cutoff`.
                      Passing it in keeps the SQL identical on Postgres and SQLite
                      (the test DB), avoiding tz-comparison issues.
        """
        # Ensure the row exists before the UPDATE so the WHERE finds something.
        await self._get_or_create(guild_id, user_id)

        stmt = (
            update(UserPetCooldown)
            .where(
                UserPetCooldown.guild_id == guild_id,
                UserPetCooldown.user_id == user_id,
                # Eligible iff never played OR the last play was at/before cutoff.
                # Both conditions are in WHERE so the check and the stamp are atomic.
                or_(
                    UserPetCooldown.last_play_at.is_(None),
                    UserPetCooldown.last_play_at <= cutoff,
                ),
            )
            .values(last_play_at=now)
            # Use "fetch" strategy so SQLAlchemy re-queries from DB when updating
            # the identity-map rather than evaluating the WHERE in Python.
            # The default "evaluate" strategy fails on SQLite (tests) when the
            # stored last_play_at is naive but our cutoff is tz-aware.
            .execution_options(synchronize_session="fetch")
        )
        r = await self.session.execute(stmt)
        await self.session.flush()
        # rowcount 1 → guard passed, slot claimed; 0 → still on cooldown.
        return r.rowcount > 0
