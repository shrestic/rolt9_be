import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class GuildSettings(Base):
    __tablename__ = "guild_settings"

    guild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("guilds.id", ondelete="CASCADE"),
        primary_key=True,
    )
    moderation: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    welcome: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    automod: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    logging: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    leveling: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    commands: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
