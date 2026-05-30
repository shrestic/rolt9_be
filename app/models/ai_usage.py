"""The `ai_usage` table — Claude tokens a guild has spent in a given UTC month.

One row per (guild, month). `tokens` is bumped atomically after each gateway call;
the gateway reads the current month's total to enforce `monthly_token_budget`.
A new month simply means a new `period_key`, so usage resets with no cleanup.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class AIUsage(Base):
    __tablename__ = "ai_usage"
    __table_args__ = (
        UniqueConstraint("guild_id", "period_key", name="uq_ai_usage_period"),
        CheckConstraint("tokens >= 0", name="ck_ai_usage_tokens_nonneg"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    guild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_key: Mapped[str] = mapped_column(String(7), nullable=False)  # "YYYY-MM"
    tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
