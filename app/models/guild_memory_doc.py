"""Bảng `guild_memory_doc` — trí nhớ markdown per-guild kiểu OpenClaw MEMORY.md.

Một doc/guild: luật server + ghi chú từng người (biệt danh/tính cách). Agent tự ghi
(tool `remember`). Luôn được nạp vào prompt Claw Agent + Companion. Cap ~4000 ký tự
(đầy thì bỏ dòng cũ nhất). Lightweight: chưa có search/vector — doc nhỏ nạp hết.
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
