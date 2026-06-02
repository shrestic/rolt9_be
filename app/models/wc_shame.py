"""Bảng `wc_shame` — lưu nick GỐC của người bị phạt đổi-nick để trả lại sang vòng mới."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class WCShame(Base):
    __tablename__ = "wc_shame"
    __table_args__ = (UniqueConstraint("guild_id", "user_discord_id", name="uq_wc_shame"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    guild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_discord_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    original_nick: Mapped[str | None] = mapped_column(String(64), nullable=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
