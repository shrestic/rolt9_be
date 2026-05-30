"""The `user_pet_cooldown` table — per-member cooldown for `/pet play`.

Playing is free, so its only limiter is a per-user cooldown (mirrors the daily
claim): one row per (guild, member) holding the last play time, flipped via a
guarded atomic UPDATE so a double-fire can't bypass the cooldown.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class UserPetCooldown(Base):
    __tablename__ = "user_pet_cooldown"
    __table_args__ = (
        # Enforce one row per (guild, member); the service layer upserts into this.
        UniqueConstraint("guild_id", "user_id", name="uq_user_pet_cooldown"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    guild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Discord snowflake — stored as BigInteger, not FK to users, because the user
    # row may not exist yet when the first play happens.
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # UTC timestamp of the last successful /pet play for this (guild, member) pair.
    # NULL means the member has never played; treat as always-eligible.
    last_play_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
