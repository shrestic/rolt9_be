"""Server-currency facade — the single entry point for bot-facing money flows.

Resolves the guild snowflake to its internal UUID, enforces the currency
on/off toggle and per-action amount cap, and delegates balance mutations to
`WalletRepository` (whose UPDATEs are atomic and never go negative). Repos flush
only; the caller's `session_scope` / `get_db` owns the commit.

Error convention:
    * `LookupError` → guild isn't registered with the bot (caller maps to a
      "this server isn't set up" reply).
    * `ValueError`  → a user-facing rejection (disabled, bad amount, no funds).
    * `grant_message_reward` is the one silent path: it returns None instead of
      raising when currency is off, because it runs on the chat hot path.
"""

import random
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.currency_config import CurrencyConfigRepository
from app.repositories.guild import GuildRepository
from app.repositories.user_wallet import WalletRepository
from app.services.currency.streak import (
    days_to_next_milestone,
    milestone_reward,
    next_streak,
    streak_bonus,
)

# Per-action cap (spec §5/§8): blocks 32/64-bit overflow, fat-finger typos, and
# runaway inflation. Transfers/admin adjustments above this are rejected.
MAX_AMOUNT = 1_000_000


@dataclass(frozen=True)
class DailyResult:
    """Outcome of a `/daily` attempt, shaped for the cog to render directly."""

    claimed: bool
    amount: int  # total granted = base + streak_bonus + milestone_bonus
    base: int  # the flat daily_amount portion
    streak_bonus: int  # escalating per-day portion
    milestone_bonus: int  # lump sum if a milestone was hit this claim (else 0)
    balance: int
    streak: int  # chain length after this claim
    days_to_milestone: int | None
    retry_after_seconds: int


@dataclass(frozen=True)
class StreakInfo:
    """Read-only streak snapshot for `/streak`."""

    current: int
    longest: int
    days_to_milestone: int | None
    enabled: bool


def _as_utc(dt: datetime) -> datetime:
    """Tag a naive datetime as UTC (SQLite can hand back naive timestamps)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _day_start(dt: datetime) -> datetime:
    """Midnight (00:00:00) UTC of the day `dt` falls on — the daily-reset line.

    `/daily` resets on the UTC calendar day rather than a rolling 24h window, so
    eligibility and the streak are anchored to this boundary: anything claimed
    before today's midnight counts as a previous day.
    """
    return _as_utc(dt).replace(hour=0, minute=0, second=0, microsecond=0)


class CurrencyService:
    def __init__(
        self,
        session: AsyncSession,
        guild_repo: GuildRepository,
        config_repo: CurrencyConfigRepository,
        wallet_repo: WalletRepository,
    ):
        self.session = session
        self.guild_repo = guild_repo
        self.config_repo = config_repo
        self.wallet_repo = wallet_repo

    async def _guild_id(self, guild_discord_id: int) -> uuid.UUID:
        """Resolve a Discord guild snowflake to our internal UUID, or raise."""
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            raise LookupError("This server isn't registered with the bot.")
        return guild.id

    async def get_balance(self, *, guild_discord_id: int, user_id: int) -> int:
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            return 0
        wallet = await self.wallet_repo.get(guild.id, user_id)
        return wallet.balance if wallet else 0

    async def grant_message_reward(self, *, guild_discord_id: int, user_id: int) -> int | None:
        """Grant passive earn for one message. Silent no-op when off/unregistered.

        Called from the XP listener only after a message has already earned XP,
        so all anti-spam + cooldown gating is inherited for free.
        """
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            return None
        cfg = await self.config_repo.get(guild.id)
        if cfg is None or not cfg.enabled:
            return None
        amount = random.randint(cfg.earn_min, cfg.earn_max)
        if amount <= 0:
            return None
        await self.wallet_repo.add_balance(guild.id, user_id, amount)
        return amount

    async def claim_daily(
        self, *, guild_discord_id: int, user_id: int, now: datetime | None = None
    ) -> DailyResult:
        gid = await self._guild_id(guild_discord_id)
        cfg = await self.config_repo.get(gid)
        if cfg is None or not cfg.enabled:
            raise ValueError("Currency isn't enabled on this server.")
        now = _as_utc(now or datetime.now(UTC))
        # Daily resets on the UTC calendar day: eligible if the last claim was
        # before today's midnight (i.e. on an earlier UTC day), not "24h ago".
        cutoff = _day_start(now)

        # Read the pre-claim state so we can compute the new streak. The atomic
        # UPDATE below only persists if the day guard still matches, so a
        # concurrent double-fire can't write a stale/duplicate streak.
        wallet = await self.wallet_repo.get_or_create(gid, user_id)
        if cfg.streak_enabled:
            last = _as_utc(wallet.last_daily_at) if wallet.last_daily_at else None
            new_streak = next_streak(last, now, wallet.current_streak)
            s_bonus = streak_bonus(
                new_streak, per_day=cfg.streak_bonus_per_day, cap=cfg.streak_bonus_cap
            )
            m_bonus = milestone_reward(new_streak)
        else:
            # Streak disabled: grant base only and drop the chain to 0. We still
            # stamp last_daily_at (the UPDATE always does) so the daily reset
            # keeps working; resetting to 0 means re-enabling later restarts the
            # chain from scratch (spec decision #6: "re-enable → count from scratch"),
            # rather than resuming the frozen count. longest_streak is preserved
            # by the max() below, so the all-time record survives.
            new_streak = 0
            s_bonus = m_bonus = 0
        new_longest = max(wallet.longest_streak, new_streak)
        total = cfg.daily_amount + s_bonus + m_bonus

        claimed = await self.wallet_repo.try_claim_daily(
            gid,
            user_id,
            amount=total,
            now=now,
            cutoff=cutoff,
            new_streak=new_streak,
            new_longest=new_longest,
        )
        wallet = await self.wallet_repo.get(gid, user_id)
        balance = wallet.balance if wallet else 0
        if claimed:
            return DailyResult(
                claimed=True,
                amount=total,
                base=cfg.daily_amount,
                streak_bonus=s_bonus,
                milestone_bonus=m_bonus,
                balance=balance,
                streak=new_streak,
                days_to_milestone=days_to_next_milestone(new_streak),
                retry_after_seconds=0,
            )
        # Already claimed today: the next claim unlocks at the next UTC midnight.
        next_reset = cutoff + timedelta(days=1)
        remaining = int((next_reset - now).total_seconds())
        return DailyResult(
            claimed=False,
            amount=0,
            base=0,
            streak_bonus=0,
            milestone_bonus=0,
            balance=balance,
            streak=wallet.current_streak if wallet else 0,
            days_to_milestone=None,
            retry_after_seconds=max(0, remaining),
        )

    async def get_streak(self, *, guild_discord_id: int, user_id: int) -> StreakInfo:
        """Read a member's streak for `/streak`. Never raises — unknown guild or
        no wallet simply reports a zero, disabled streak."""
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            return StreakInfo(current=0, longest=0, days_to_milestone=None, enabled=False)
        cfg = await self.config_repo.get(guild.id)
        enabled = bool(cfg and cfg.enabled and cfg.streak_enabled)
        wallet = await self.wallet_repo.get(guild.id, user_id)
        current = wallet.current_streak if wallet else 0
        longest = wallet.longest_streak if wallet else 0
        return StreakInfo(
            current=current,
            longest=longest,
            days_to_milestone=days_to_next_milestone(current),
            enabled=enabled,
        )

    async def pay(
        self, *, guild_discord_id: int, sender_id: int, receiver_id: int, amount: int
    ) -> int:
        """Transfer `amount` from sender to receiver. Returns sender's new balance.

        Atomic two-step in one transaction: debit the sender with the guarded
        UPDATE (fails ⇒ insufficient funds, raise and nothing changed), then
        credit the receiver. Both live in the caller's transaction, so a failure
        rolls back the whole thing — money is never created or lost.
        """
        gid = await self._guild_id(guild_discord_id)
        cfg = await self.config_repo.get(gid)
        if cfg is None or not cfg.enabled:
            raise ValueError("Currency isn't enabled on this server.")
        if not cfg.allow_pay:
            raise ValueError("Transfers are disabled on this server.")
        if amount <= 0 or amount > MAX_AMOUNT:
            raise ValueError(f"Amount must be between 1 and {MAX_AMOUNT:,}.")
        if sender_id == receiver_id:
            raise ValueError("You can't pay yourself.")
        ok = await self.wallet_repo.add_balance(gid, sender_id, -amount)
        if not ok:
            balance = await self.get_balance(guild_discord_id=guild_discord_id, user_id=sender_id)
            raise ValueError(f"Not enough funds — you only have {balance:,}.")
        await self.wallet_repo.add_balance(gid, receiver_id, amount)
        sender_wallet = await self.wallet_repo.get(gid, sender_id)
        return sender_wallet.balance if sender_wallet else 0

    async def admin_add(self, *, guild_discord_id: int, user_id: int, delta: int) -> int:
        """Admin give (delta>0) / take (delta<0). Returns the new balance.

        A take that exceeds the balance fails the atomic guard ⇒ we raise rather
        than silently clamping, so the admin knows it didn't fully apply.
        """
        gid = await self._guild_id(guild_discord_id)
        if abs(delta) > MAX_AMOUNT:
            raise ValueError(f"Amount must be at most {MAX_AMOUNT:,}.")
        ok = await self.wallet_repo.add_balance(gid, user_id, delta)
        if not ok:
            balance = (await self.wallet_repo.get(gid, user_id)).balance
            raise ValueError(f"Can only take up to {balance:,}.")
        wallet = await self.wallet_repo.get(gid, user_id)
        return wallet.balance

    async def admin_set(self, *, guild_discord_id: int, user_id: int, value: int) -> int:
        """Set an absolute balance (admin override / reset to 0)."""
        gid = await self._guild_id(guild_discord_id)
        if value < 0:
            raise ValueError("Balance can't be negative.")
        wallet = await self.wallet_repo.set_balance(gid, user_id, value)
        return wallet.balance

    async def leaderboard(self, *, guild_discord_id: int, limit: int, offset: int):
        """Return (rows, total) of richest members for `/baltop` and REST."""
        gid = await self._guild_id(guild_discord_id)
        return await self.wallet_repo.leaderboard(gid, limit=limit, offset=offset)
