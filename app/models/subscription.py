"""Bảng `subscription` — đăng ký nhận tin ĐỊNH KỲ hằng ngày (vd 'tin chứng khoán 8h sáng').

Khác `reminder` (một lần): subscription LẶP mỗi ngày và lấy tin TƯƠI mỗi lần (web search +
AI tóm tắt). Tới giờ HH:MM (giờ VN) scheduler đăng vào `channel_id`. `last_run_on` = ngày VN
chạy gần nhất, để mỗi ngày chỉ đăng 1 lần. `active=False` (hoặc xoá) khi user bảo ngừng.
`topic` là free-text nên đăng ký được bất cứ chủ đề gì (chứng khoán, vàng, thời tiết, bóng đá...).
"""

import datetime
import uuid

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class Subscription(Base):
    __tablename__ = "subscription"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    creator_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Mỗi đăng ký là 1 trong 2 chế độ:
    #  - topic   != None: tới giờ TRA WEB + AI tóm tắt (bản tin định kỳ, vd 'giá vàng').
    #  - message != None: tới giờ chỉ PING câu đó (nhắc cá nhân lặp lại, vd 'đi về').
    topic: Mapped[str | None] = mapped_column(Text, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    hour: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-23, giờ VN đăng mỗi ngày
    minute: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    # Ngày VN chạy gần nhất — để mỗi ngày chỉ đăng 1 lần (None = chưa chạy lần nào).
    last_run_on: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
