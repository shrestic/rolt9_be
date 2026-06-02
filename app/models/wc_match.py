"""Bảng `wc_match` — trận World Cup sync từ API, DÙNG CHUNG mọi guild."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class WCMatch(Base):
    __tablename__ = "wc_match"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    competition: Mapped[str] = mapped_column(String(16), nullable=False, default="WC")
    stage: Mapped[str | None] = mapped_column(String(40), nullable=True)
    matchday: Mapped[int | None] = mapped_column(Integer, nullable=True)
    home_team: Mapped[str] = mapped_column(String(64), nullable=False)
    home_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    away_team: Mapped[str] = mapped_column(String(64), nullable=False)
    away_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    kickoff_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="scheduled")
    home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ou_line: Mapped[float] = mapped_column(Float, nullable=False, default=2.5)
    handicap_team: Mapped[str | None] = mapped_column(String(8), nullable=True)
    handicap_line: Mapped[float | None] = mapped_column(Float, nullable=True)
    settled: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
