"""The `guild_minigame_config` table — per-guild mini-games settings.

One row per guild (PK = guild_id). Off by default. Holds the bet bounds an admin
tunes; the house edge is fixed in code (see minigame_logic). No per-user state —
a round is just an atomic wallet delta.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class GuildMinigameConfig(Base):
    __tablename__ = "guild_minigame_config"
    __table_args__ = (
        CheckConstraint("min_bet >= 1", name="ck_minigame_min_bet_pos"),
        CheckConstraint("max_bet >= 1", name="ck_minigame_max_bet_pos"),
        CheckConstraint("min_bet <= max_bet", name="ck_minigame_bet_range"),
    )

    guild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    min_bet: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    max_bet: Mapped[int] = mapped_column(Integer, nullable=False, default=10_000)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
