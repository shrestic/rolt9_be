"""Bảng `agent_message` — lịch sử hội thoại ngắn hạn của Claw Agent.

Mỗi row là 1 lượt (user hoặc assistant), gom theo `conversation_id`. Lượt assistant
lưu `discord_message_id` để khi user reply vào tin bot, ta tra ngược ra cuộc hội
thoại để nối tiếp. PK `id` là số nguyên tự tăng → thứ tự chèn xác định (KHÔNG dựa
created_at vì trong 1 transaction Postgres mọi now() bằng nhau). Chỉ nạp N lượt gần
nhất vào prompt; row cũ vẫn nằm lại (chưa dọn).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class AgentMessage(Base):
    __tablename__ = "agent_message"
    __table_args__ = (
        CheckConstraint("role in ('user','assistant')", name="ck_agent_message_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    discord_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
