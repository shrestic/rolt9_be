"""The `wc_prediction` table — a user's prediction for a (match, bet type) in a guild."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class WCPrediction(Base):
    __tablename__ = "wc_prediction"
    __table_args__ = (
        UniqueConstraint(
            "guild_id", "match_id", "user_discord_id", "bet_type", name="uq_wc_prediction"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    match_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("wc_match.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_discord_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    bet_type: Mapped[str] = mapped_column(String(8), nullable=False)
    pick: Mapped[str] = mapped_column(String(32), nullable=False)
    points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
