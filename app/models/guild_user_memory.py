"""Bảng `guild_user_memory` — trí nhớ dài hạn per-user-per-guild của Claw Agent.

Một row mỗi (guild, user). `facts` là danh sách dòng (mỗi dòng 1 fact), do bot tự
rút sau mỗi lượt (auto-extract) và cap lại. Riêng tư: chỉ phạm vi guild; user tự
xoá bằng /claw-forget.
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
