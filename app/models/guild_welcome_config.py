"""The `guild_welcome_config` table — per-guild welcome/leave plugin settings.

One row per guild (PK = guild_id). Off by default. Holds the channel to post in,
the welcome/leave message templates (with {user}/{server}/{count} placeholders),
and toggles — including `ai_welcome` to generate the greeting via Claude (falling
back to the template when AI is off/over budget).
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base

DEFAULT_WELCOME = "Chào mừng {user} đến với {server}! 🎉 Bạn là thành viên thứ {count}."
DEFAULT_LEAVE = "{user} đã rời khỏi **{server}**. 👋"


class GuildWelcomeConfig(Base):
    __tablename__ = "guild_welcome_config"

    guild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Snowflake of the channel welcome/leave messages are posted to. NULL = unset.
    channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    welcome_template: Mapped[str] = mapped_column(
        String(1000), nullable=False, default=DEFAULT_WELCOME
    )
    # When True (and AI is enabled+funded), generate the greeting via Claude.
    ai_welcome: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    leave_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    leave_template: Mapped[str] = mapped_column(String(1000), nullable=False, default=DEFAULT_LEAVE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
