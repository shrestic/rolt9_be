"""Usage AI của guild trong một tháng UTC: token (hiển thị) + cost USD (chặn budget).

Một row mỗi (guild, month). `tokens` và `cost_usd` được cộng atomic sau mỗi lần
gọi gateway; gateway đọc cost tháng hiện tại để so với budget. Sang tháng mới =
`period_key` mới nên usage tự reset, không cần dọn dẹp.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class AIUsage(Base):
    __tablename__ = "ai_usage"
    __table_args__ = (
        UniqueConstraint("guild_id", "period_key", name="uq_ai_usage_period"),
        CheckConstraint("tokens >= 0", name="ck_ai_usage_tokens_nonneg"),
        CheckConstraint("cost_usd >= 0", name="ck_ai_usage_cost_nonneg"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    guild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_key: Mapped[str] = mapped_column(String(7), nullable=False)  # "YYYY-MM"
    tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
