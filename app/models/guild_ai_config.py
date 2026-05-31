"""Cấu hình AI per-guild (BYO-key v2).

Một row mỗi guild (PK = guild_id), tắt mặc định. Server tự nhập API key (lưu mã
hóa Fernet ở `api_key_enc`), chọn `provider`/`model` từ catalog, và bị chặn theo
`monthly_budget_usd` (USD/tháng) — gateway từ chối khi cost tháng vượt trần. Chưa
nhập key/provider/model => AI coi như chưa cấu hình (không fallback key global).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    LargeBinary,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class GuildAIConfig(Base):
    __tablename__ = "guild_ai_config"
    __table_args__ = (CheckConstraint("monthly_budget_usd >= 0", name="ck_ai_budget_nonneg"),)

    guild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Provider/model từ catalog (vd "anthropic" / "claude-haiku-4-5"). "" = chưa chọn.
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # API key của server, mã hóa Fernet. NULL = chưa nhập (AI tắt, không fallback global).
    api_key_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # Trần chi phí USD/tháng. Gateway chặn khi cost tháng >= giá trị này.
    monthly_budget_usd: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False, default=5.0)
    # Persona server-wide cho /chat. "" = persona thân thiện mặc định (ChatService).
    persona: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    # Claw Agent (hội thoại on_message). Toggle riêng, độc lập với `enabled`.
    agent_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Nếu set → agent chỉ trả lời trong kênh này; NULL = mọi kênh.
    agent_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Cho phép Claw Agent gọi tool (web search + tra cứu). Admin tắt để khỏi tốn search.
    tools_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Cho phép Claw Agent làm HÀNH ĐỘNG server (role/mod/toggle). Opt-in, mặc định tắt.
    actions_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
