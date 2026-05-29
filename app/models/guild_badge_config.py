"""The `guild_badge_config` table — per-guild badges on/off switch.

One row per guild (PK = guild_id). Like leveling and currency, badges are
**off by default**: a freshly-created row (made on first read) means "badges
exist but are disabled" until an admin turns them on from the dashboard.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class GuildBadgeConfig(Base):
    __tablename__ = "guild_badge_config"

    guild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True
    )
    # Master switch. When False, BadgeService.award_new / list_for report disabled.
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
