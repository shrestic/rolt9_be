import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.colors import RankCardColors
from app.core.enums import BgType
from app.db.base_class import Base


class UserRankCardTheme(Base):
    __tablename__ = "user_rank_card_theme"
    __table_args__ = (
        UniqueConstraint("guild_id", "user_id", name="uq_user_rank_card_theme_guild_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    guild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("guilds.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    bg_type: Mapped[BgType] = mapped_column(
        Enum(BgType, name="bg_type", values_callable=lambda x: [m.value for m in x]),
        nullable=False,
        default=BgType.GRADIENT,
    )
    bg_color_1: Mapped[str] = mapped_column(
        String(7), nullable=False, default=RankCardColors.DEFAULT_BG_PRIMARY
    )
    bg_color_2: Mapped[str] = mapped_column(
        String(7), nullable=False, default=RankCardColors.DEFAULT_BG_SECONDARY
    )
    accent_color: Mapped[str] = mapped_column(
        String(7), nullable=False, default=RankCardColors.DEFAULT_ACCENT
    )
    text_color: Mapped[str] = mapped_column(
        String(7), nullable=False, default=RankCardColors.DEFAULT_TEXT
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
