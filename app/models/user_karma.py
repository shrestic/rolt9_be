"""The `user_karma` table — total reputation points a member has *received*.

One row per (guild, member); `points` only goes up (peer upvotes, no downvote).
Indexed by (guild_id, points) for the leaderboard. A row is created lazily the
first time the member receives karma.
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


class UserKarma(Base):
    __tablename__ = "user_karma"
    __table_args__ = (
        UniqueConstraint("guild_id", "user_id", name="uq_user_karma_guild_user"),
        Index("ix_user_karma_leaderboard", "guild_id", "points"),
        CheckConstraint("points >= 0", name="ck_user_karma_points_nonneg"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    guild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
