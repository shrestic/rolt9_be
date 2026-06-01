"""Bảng `agent_message` — lịch sử hội thoại ngắn hạn của Claw Agent.

Mỗi row là 1 lượt (user hoặc assistant), gom theo `conversation_id`. Lượt assistant
lưu `discord_message_id` để khi user reply vào tin bot, ta tra ngược ra cuộc hội
thoại để nối tiếp. PK `id` là số nguyên tự tăng → thứ tự chèn xác định (KHÔNG dựa
created_at vì trong 1 transaction Postgres mọi now() bằng nhau). Chỉ nạp N lượt gần
nhất vào prompt; row cũ vẫn nằm lại (chưa dọn).

`channel_id` + `user_discord_id` được gắn vào MỌI lượt của cuộc (kể cả lượt assistant,
nó mang theo kênh/người mà bot đang trả lời). Nhờ vậy khi user nhắn tiếp mà KHÔNG reply,
ta vẫn tra được "cuộc gần nhất của (kênh, người) trong X phút" để nối tiếp tự nhiên
(xem `AgentMessageRepository.latest_conversation`). Cả hai nullable để tương thích row cũ.
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
        # Tra "cuộc gần nhất của (kênh, người)" — lọc theo 3 cột, sắp theo id giảm dần.
        Index(
            "ix_agent_message_guild_channel_user",
            "guild_id",
            "channel_id",
            "user_discord_id",
        ),
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
    # Kênh + người của cuộc — để nối cuộc gần nhất khi user không reply (window-based).
    channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    user_discord_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
