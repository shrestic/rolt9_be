"""The `guild_user_memory` table — per-user-per-guild long-term SERVER MEMORY of the Claw Agent.

One row per (guild, user). `facts` is a list of lines (one fact per line), which the bot
extracts itself after each turn (auto-extract) and caps. Private: scoped to the guild only;
users delete their own with /claw-forget.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class GuildUserMemory(Base):
    __tablename__ = "guild_user_memory"

    guild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True
    )
    user_discord_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    facts: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
