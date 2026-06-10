"""Per-guild AI config (BYO-key v2).

One row per guild (PK = guild_id), off by default. The server enters its own API key
(stored Fernet-encrypted in `api_key_enc`), picks a `provider`/`model` from the catalog,
and is gated by `monthly_budget_usd` (USD/month) — the gateway rejects calls when the
month's cost exceeds the cap. Without a key/provider/model, AI is treated as
unconfigured (no fallback to a global key).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
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
    # Provider/model from the catalog (e.g. "anthropic" / "claude-haiku-4-5"). "" = not chosen yet.
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # The server's API key, Fernet-encrypted. NULL = not entered (AI off, no global fallback).
    api_key_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # Cost cap in USD/month. The gateway blocks when the month's cost >= this value.
    monthly_budget_usd: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False, default=5.0)
    # Server-wide persona for /chat. "" = default friendly persona (ChatService).
    persona: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    # Claw Agent (on_message conversation). Separate toggle, independent of `enabled`.
    agent_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # If set → the agent only replies in this channel; NULL = any channel.
    agent_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Allow the Claw Agent to call tools (web search + lookups). Admins turn off to avoid search costs.
    tools_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Allow the Claw Agent to perform server ACTIONS (role/mod/toggle). Opt-in, off by default.
    actions_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Server Companion AI — the bot observes and chimes in on its own (proactive). Opt-in.
    companion_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    companion_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    companion_cooldown_min: Mapped[int] = mapped_column(Integer, nullable=False, default=45)
    # Timestamp (UTC) of the companion bot's most recent POST — STORED in DB so the cooldown SURVIVES restart/deploy
    # (previously kept in RAM, so each restart forgot it -> re-spammed). NULL = never posted.
    companion_last_post_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
