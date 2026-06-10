"""The `guild_wc_config` table — enable/disable + channel + shame nickname prefix for WC Predict (per-guild)."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base

DEFAULT_SHAME_PREFIX = "🤡 Amateur — "


class GuildWCConfig(Base):
    __tablename__ = "guild_wc_config"

    guild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    shame_nick_prefix: Mapped[str] = mapped_column(
        String(40), nullable=False, default=DEFAULT_SHAME_PREFIX
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
