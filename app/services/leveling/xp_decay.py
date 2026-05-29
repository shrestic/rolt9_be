"""Inactivity-based XP decay sweep.

Erodes XP from members who have stopped chatting. Per-guild, opt-in (the
`xp_decay_enabled` config flag), and **floored at the member's current level**
so a decay never drops a level or strips a reward role — it only eats progress
within the current level. The sweep touches the database only; it makes no
Discord calls and sends no notifications, by design.

Two layers:

    XpDecaySweeper.decay_page  — applies decay to one id-ordered page of rows
                                 inside the caller's session (flush only).
    sweep_inactive_xp          — drives the pages to completion, each in its
                                 own `session_scope` (one commit per batch),
                                 so no single transaction spans the whole table.

The sweep is global (all guilds at once), so it intentionally does not route
through the per-guild `LevelingService` facade.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import session_scope
from app.repositories.user_xp import UserXpRepository
from app.services.leveling.xp_calculator import (
    apply_decay,
    level_for_xp,
    total_xp_for_level,
)

log = logging.getLogger(__name__)

# Rows per batch. Each batch is one transaction; keep it modest so a large
# table doesn't produce one giant long-running transaction.
DEFAULT_BATCH_SIZE = 500


@dataclass(frozen=True)
class DecayPage:
    """Outcome of decaying one page.

    Attributes:
        scanned: How many candidate rows the page contained. When this is less
            than the requested limit, the cursor has reached the end.
        last_id: The id of the last row scanned (the next page's `after_id`).
            None when the page was empty.
        decayed: How many rows actually lost XP (excludes rows already at floor
            or not yet past their inactivity period).
    """

    scanned: int
    last_id: uuid.UUID | None
    decayed: int


def _as_utc(dt: datetime) -> datetime:
    """Tag a possibly-naive datetime as UTC.

    Some engines (SQLite in tests) return naive datetimes from `timezone=True`
    columns; this keeps subtraction with an aware `now` safe.
    """
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class XpDecaySweeper:
    """Applies decay to pages of `user_xp` rows. Flushes; never commits."""

    def __init__(self, session: AsyncSession, xp_repo: UserXpRepository):
        self.session = session
        self.xp_repo = xp_repo

    def _anchor(self, row) -> datetime:
        """The instant from which inactivity is measured for `row`.

        The later of last activity (`last_xp_at`) and last settled decay
        (`last_decay_at`); falls back to `created_at` when a row has neither
        (e.g. admin-granted XP with no chat activity yet).
        """
        candidates = [t for t in (row.last_xp_at, row.last_decay_at) if t is not None]
        anchor = max(candidates) if candidates else row.created_at
        return _as_utc(anchor)

    @staticmethod
    def _periods(now: datetime, anchor: datetime, days: int) -> int:
        """Number of full inactivity periods between `anchor` and `now`."""
        elapsed = (now - anchor).total_seconds()
        if elapsed <= 0:
            return 0
        return int(elapsed // (days * 86400))

    async def decay_page(
        self, *, now: datetime, after_id: uuid.UUID | None, limit: int
    ) -> DecayPage:
        """Decay one id-ordered page of eligible rows.

        For each row: compute how many full periods have elapsed; if >= 1,
        decay (compounded, floored at the current level threshold) and advance
        `last_decay_at` to the settled boundary so the next sweep resumes from
        there. Rows not yet due are left untouched.
        """
        rows = await self.xp_repo.fetch_decay_page(after_id=after_id, limit=limit)
        decayed = 0
        last_id: uuid.UUID | None = after_id
        for row, percent, days in rows:
            last_id = row.id
            anchor = self._anchor(row)
            periods = self._periods(now, anchor, days)
            if periods <= 0:
                continue
            floor = total_xp_for_level(level_for_xp(row.total_xp))
            new_total = apply_decay(
                row.total_xp, level_floor=floor, percent=percent, periods=periods
            )
            row.last_decay_at = anchor + timedelta(days=days * periods)
            if new_total != row.total_xp:
                row.total_xp = new_total
                decayed += 1
        await self.session.flush()
        return DecayPage(scanned=len(rows), last_id=last_id, decayed=decayed)


async def sweep_inactive_xp(
    *,
    now: datetime,
    batch_size: int = DEFAULT_BATCH_SIZE,
    scope=session_scope,
) -> int:
    """Run the full decay sweep, one batch (and one transaction) at a time.

    Args:
        now: The reference instant for all inactivity math (captured once by
            the caller so the whole sweep is consistent).
        batch_size: Rows per batch / transaction.
        scope: Async context manager factory yielding a session. Defaults to
            `session_scope`; injectable for tests.

    Returns:
        Total number of rows that lost XP across the whole sweep.
    """
    total = 0
    after_id: uuid.UUID | None = None
    while True:
        async with scope() as session:
            sweeper = XpDecaySweeper(session, UserXpRepository(session))
            page = await sweeper.decay_page(now=now, after_id=after_id, limit=batch_size)
        total += page.decayed
        if page.scanned < batch_size:
            break
        after_id = page.last_id
    return total
