"""The `user_wallet` table — one server-currency balance per (guild, member).

Mirrors `user_xp`: a server's economy is scoped to that guild, so the same
Discord user has an independent balance in every server. A row is created
lazily the first time a member earns/receives currency (see
`WalletRepository.get_or_create`), so "no row" simply means "balance 0".
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class UserWallet(Base):
    __tablename__ = "user_wallet"
    __table_args__ = (
        # One wallet per member per guild.
        UniqueConstraint("guild_id", "user_id", name="uq_user_wallet_guild_user"),
        # Covers the `/baltop` + dashboard leaderboard query (ORDER BY balance
        # within a guild) so it doesn't have to scan the whole table.
        Index("ix_user_wallet_leaderboard", "guild_id", "balance"),
        # Defence-in-depth: the app only mutates balance through a guarded
        # atomic UPDATE, but this makes a negative balance impossible even for
        # a direct/buggy SQL write.
        CheckConstraint("balance >= 0", name="ck_user_wallet_balance_nonneg"),
        # Streak counters can never be negative.
        CheckConstraint("current_streak >= 0", name="ck_user_wallet_streak_nonneg"),
        CheckConstraint("longest_streak >= 0", name="ck_user_wallet_longest_nonneg"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    guild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("guilds.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Discord snowflake of the member. BigInteger because snowflakes exceed 32-bit.
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # BigInteger (64-bit), NOT Integer: a long-lived/active economy or admin
    # grants could otherwise overflow the ~2.1B Integer ceiling.
    balance: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # When the member last successfully claimed `/daily`. NULL = never claimed.
    # The daily-claim UPDATE compares against this to enforce the 24h cooldown.
    last_daily_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Consecutive-day claim chain. Bumped/reset by `/daily` (see streak.py).
    current_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # All-time best streak — for the `/streak` flex and future badges.
    longest_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
