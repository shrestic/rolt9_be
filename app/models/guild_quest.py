"""The `guild_quest` table — admin-defined quest templates.

One row per quest an admin creates from the dashboard. A quest says *what to do*
(objective_type reaching target within a period) and *what you get* (reward_coins).
Progress against it is tracked per member per period in `user_quest_progress`.
Unlike badges, quests are NOT hardcoded — each guild authors its own.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class GuildQuest(Base):
    __tablename__ = "guild_quest"
    __table_args__ = (
        CheckConstraint("target > 0", name="ck_quest_target_pos"),
        CheckConstraint("reward_coins >= 0", name="ck_quest_reward_nonneg"),
        Index("ix_guild_quest_enabled", "guild_id", "enabled"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    guild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    period: Mapped[str] = mapped_column(String(16), nullable=False)
    objective_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target: Mapped[int] = mapped_column(Integer, nullable=False)
    reward_coins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
