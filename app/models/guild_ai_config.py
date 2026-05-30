"""The `guild_ai_config` table — per-guild AI on/off + monthly token budget.

One row per guild (PK = guild_id). Off by default. `monthly_token_budget` caps
how many Claude tokens the guild can spend per UTC month (the gateway refuses
calls once `ai_usage` for the month reaches it) — the cost guard.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class GuildAIConfig(Base):
    __tablename__ = "guild_ai_config"
    __table_args__ = (CheckConstraint("monthly_token_budget >= 0", name="ck_ai_budget_nonneg"),)

    guild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    monthly_token_budget: Mapped[int] = mapped_column(Integer, nullable=False, default=100_000)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
