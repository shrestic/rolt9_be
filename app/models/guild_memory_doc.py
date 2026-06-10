"""The `guild_memory_doc` table — per-guild markdown SERVER MEMORY, OpenClaw MEMORY.md style.

One doc per guild: server rules + notes on each person (nickname/personality). The agent
writes it itself (the `remember` tool). Always loaded into the Claw Agent + Companion
prompt. Capped at ~4000 characters (when full, the oldest line is dropped). Lightweight:
no search/vector yet — the small doc is loaded in full.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class GuildMemoryDoc(Base):
    __tablename__ = "guild_memory_doc"

    guild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True
    )
    doc: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
