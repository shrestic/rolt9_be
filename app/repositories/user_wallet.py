"""Data access for `user_wallet` (server-currency balances).

The important design choice here is **atomicity**: every balance change goes
through a single guarded SQL UPDATE rather than a read-modify-write in Python.
That makes overdrafts and double-claims impossible without any application-level
lock — the database itself arbitrates concurrent `/pay`, `/daily`, and passive
earns. Repositories only `flush()`; the surrounding `get_db` / `session_scope`
owns the commit (Unit-of-Work pattern, same as every other repo).
"""

import uuid
from datetime import datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_wallet import UserWallet


class WalletRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, guild_id: uuid.UUID, user_id: int) -> UserWallet | None:
        """Return the wallet row, or None if the member has never had one."""
        r = await self.session.execute(
            select(UserWallet).where(UserWallet.guild_id == guild_id, UserWallet.user_id == user_id)
        )
        return r.scalar_one_or_none()

    async def get_or_create(self, guild_id: uuid.UUID, user_id: int) -> UserWallet:
        """Return the wallet, creating a zero-balance row on first access.

        Wallets are created lazily (a member only gets a row once they first
        earn/receive). `flush()` materialises the row's PK so callers can use it
        immediately within the same transaction.
        """
        existing = await self.get(guild_id, user_id)
        if existing is not None:
            return existing
        row = UserWallet(guild_id=guild_id, user_id=user_id, balance=0)
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def add_balance(self, guild_id: uuid.UUID, user_id: int, delta: int) -> bool:
        """Atomically apply `delta` to the balance, refusing to go below zero.

        Used for every earn/spend: passive earn (+), receiving a transfer (+),
        sending one (−), admin give/take (±).

        Returns:
            True if the balance changed; False (and nothing changes) when a
            negative `delta` would overdraw.

        Why a guarded UPDATE instead of read-then-write: the condition
        `balance + delta >= 0` lives in the WHERE clause, so the check and the
        write are one atomic statement. Two concurrent spends therefore can't
        both "see enough money" and both succeed — at most one matches.
        """
        # Make sure a row exists first; a positive grant to a brand-new member
        # must land somewhere, and for a spend the WHERE simply matches 0 rows.
        await self.get_or_create(guild_id, user_id)
        stmt = (
            update(UserWallet)
            .where(
                UserWallet.guild_id == guild_id,
                UserWallet.user_id == user_id,
                # The overdraft guard — and the whole reason this is race-safe.
                UserWallet.balance + delta >= 0,
            )
            .values(balance=UserWallet.balance + delta)
        )
        r = await self.session.execute(stmt)
        await self.session.flush()
        # rowcount 0 ⇒ the guard failed (insufficient funds); 1 ⇒ applied.
        return r.rowcount > 0

    async def try_claim_daily(
        self,
        guild_id: uuid.UUID,
        user_id: int,
        *,
        amount: int,
        now: datetime,
        cutoff: datetime,
        new_streak: int,
        new_longest: int,
    ) -> bool:
        """Atomically claim the daily reward; True if claimed, False if on cooldown.

        Like `add_balance`, the cooldown test lives in the WHERE clause
        (`last_daily_at IS NULL OR last_daily_at <= cutoff`), so two `/daily`
        commands fired at almost the same instant can't both pass — only one
        UPDATE matches, the other reports cooldown. This closes the
        double-claim race that a read-then-write would leave open.

        Streak counters are computed by the caller (from the pre-claim wallet
        state) and passed in as plain values. That's safe despite the
        read-then-compute gap: only the single UPDATE whose WHERE still matches
        actually writes, so a losing concurrent claim never persists its
        (would-be stale) streak.

        Args:
            amount: How much to grant (base + streak bonus + milestone).
            now: Timestamp to stamp into `last_daily_at` on success.
            cutoff: `now - 24h`, computed by the caller. Passing it in (rather
                than using SQL `now() - interval`) keeps the statement identical
                on Postgres and on SQLite used in tests.
            new_streak: The chain count to store on success.
            new_longest: `max(old_longest, new_streak)`, computed by the caller.
        """
        await self.get_or_create(guild_id, user_id)
        stmt = (
            update(UserWallet)
            .where(
                UserWallet.guild_id == guild_id,
                UserWallet.user_id == user_id,
                # Eligible iff never claimed, or the last claim is older than 24h.
                or_(UserWallet.last_daily_at.is_(None), UserWallet.last_daily_at <= cutoff),
            )
            .values(
                balance=UserWallet.balance + amount,
                last_daily_at=now,
                current_streak=new_streak,
                longest_streak=new_longest,
            )
            # Use "fetch" so SQLAlchemy re-selects from the DB when updating the
            # identity-map instead of evaluating the WHERE clause in Python.
            # The default "evaluate" strategy fails on SQLite (tests) when the
            # stored last_daily_at is naive but our cutoff is tz-aware.
            .execution_options(synchronize_session="fetch")
        )
        r = await self.session.execute(stmt)
        await self.session.flush()
        return r.rowcount > 0

    async def set_balance(self, guild_id: uuid.UUID, user_id: int, value: int) -> UserWallet:
        """Set an absolute balance (admin override / reset). No cooldown logic."""
        row = await self.get_or_create(guild_id, user_id)
        row.balance = value
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def leaderboard(
        self, guild_id: uuid.UUID, *, limit: int = 20, offset: int = 0
    ) -> tuple[list[UserWallet], int]:
        """Return one page of the richest members + the total wallet count.

        Ordered by balance DESC with a stable `user_id ASC` tie-break so paging
        is deterministic. Backed by the `(guild_id, balance)` index.
        """
        total_r = await self.session.execute(
            select(func.count()).select_from(UserWallet).where(UserWallet.guild_id == guild_id)
        )
        total = int(total_r.scalar_one())
        r = await self.session.execute(
            select(UserWallet)
            .where(UserWallet.guild_id == guild_id)
            .order_by(UserWallet.balance.desc(), UserWallet.user_id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(r.scalars().all()), total

    async def rank_of(self, guild_id: uuid.UUID, user_id: int) -> int | None:
        """Return the member's 1-indexed rank by balance, or None if no wallet.

        Rank = (number of members richer than them) + 1 — computed with a COUNT
        rather than materialising the whole leaderboard.
        """
        target = await self.get(guild_id, user_id)
        if target is None:
            return None
        r = await self.session.execute(
            select(func.count())
            .select_from(UserWallet)
            .where(UserWallet.guild_id == guild_id, UserWallet.balance > target.balance)
        )
        return int(r.scalar_one()) + 1
