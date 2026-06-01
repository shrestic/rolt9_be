"""Bảng `reminder` — nhắc hẹn đặt trước (báo thức).

Mỗi row là 1 lời nhắc: tới `remind_at` (lưu UTC) thì scheduler gửi vào `channel_id`,
@ping những người trong `target_ids`. Lưu trong DB (KHÔNG phải trí nhớ AI) nên sống sót
qua restart và cả tuần/tháng sau vẫn nhắc đúng. `fired` đánh dấu đã nhắc để không lặp.
`target_ids` là JSON list các Discord user id (số) cần tag.
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class Reminder(Base):
    __tablename__ = "reminder"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    creator_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Danh sách user id (số) cần @ping khi tới giờ. JSON cho gọn (portable SQLite + PG).
    target_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # Thời điểm nhắc — LƯU UTC (tz-aware). Index để query "cái nào tới giờ" nhanh.
    remind_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    fired: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
