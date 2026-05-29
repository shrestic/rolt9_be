"""The `guild_currency_config` table — per-guild server-currency settings.

One row per guild (PK = guild_id). Holds the on/off switch plus every knob an
admin tunes from the dashboard: what the currency is called, how much chatting
earns, the daily reward, and whether members may transfer to each other. Like
leveling, currency is **off by default** — a fresh row (created on first read)
means "currency exists but disabled".
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class GuildCurrencyConfig(Base):
    __tablename__ = "guild_currency_config"
    # Defence-in-depth: the Pydantic schema validates dashboard input, but these
    # DB-level checks make impossible states unrepresentable even for direct SQL
    # writes — non-negative amounts, and a coherent earn range (min ≤ max).
    __table_args__ = (
        CheckConstraint("earn_min >= 0", name="ck_currency_earn_min_nonneg"),
        CheckConstraint("earn_max >= 0", name="ck_currency_earn_max_nonneg"),
        CheckConstraint("earn_min <= earn_max", name="ck_currency_earn_range"),
        CheckConstraint("daily_amount >= 0", name="ck_currency_daily_nonneg"),
    )

    guild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("guilds.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # Master switch. When False, passive earn / /daily / /pay all no-op.
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Display name + emoji of the currency, e.g. "xu" 🪙. Shown in every reply.
    currency_name: Mapped[str] = mapped_column(String(32), nullable=False, default="coins")
    currency_emoji: Mapped[str] = mapped_column(String(32), nullable=False, default="🪙")
    # Passive earn: each message that earns XP also grants a random amount in
    # [earn_min, earn_max] (inclusive). earn_min == earn_max ⇒ a fixed amount.
    earn_min: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    earn_max: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    # Reward granted by `/daily`, claimable once per 24h.
    daily_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    # Whether members can transfer to each other via `/pay`.
    allow_pay: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
