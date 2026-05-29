import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.colors import RankCardColors
from app.core.enums import BgType
from app.db.base_class import Base


class GuildRankCardTheme(Base):
    __tablename__ = "guild_rank_card_theme"

    guild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("guilds.id", ondelete="CASCADE"),
        primary_key=True,
    )
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
