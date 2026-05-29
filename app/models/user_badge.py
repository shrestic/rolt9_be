"""The `user_badge` table — one row per (guild, member, badge) earned.

A row's existence *is* the fact "this member has this badge". Badges are
permanent: rows are inserted on award and never deleted, and the unique
constraint makes a badge un-duplicatable. `badge_key` references a `BadgeDef.key`
in the hardcoded catalog (`app/services/badges/catalog.py`) — it is a logical
reference, not a FK, because the catalog lives in code, not a table.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class UserBadge(Base):
    __tablename__ = "user_badge"
    __table_args__ = (
        # A member can hold each badge at most once.
        UniqueConstraint("guild_id", "user_id", "badge_key", name="uq_user_badge"),
        # Covers the /badges lookup (all badges for one member in a guild).
        Index("ix_user_badge_member", "guild_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    guild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Stable catalog key, e.g. "level_10". Logical ref to BadgeDef.key (code).
    badge_key: Mapped[str] = mapped_column(String(64), nullable=False)
    earned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
