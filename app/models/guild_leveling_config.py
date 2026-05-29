import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import LevelRoleMode, NotificationMode
from app.db.base_class import Base


class GuildLevelingConfig(Base):
    __tablename__ = "guild_leveling_config"
    # Defence-in-depth: Pydantic validates HTTP input, but direct SQL writes
    # (admin scripts, future migrations, broken tests) bypass it. These DB
    # constraints make impossible states impossible — `xp_min > xp_max` or
    # negative cooldowns simply can't land in this table.
    __table_args__ = (
        CheckConstraint("xp_min >= 1", name="ck_guild_leveling_config_xp_min_positive"),
        CheckConstraint("xp_max >= 1", name="ck_guild_leveling_config_xp_max_positive"),
        CheckConstraint("xp_min <= xp_max", name="ck_guild_leveling_config_xp_range"),
        CheckConstraint("cooldown_seconds >= 0", name="ck_guild_leveling_config_cooldown_nonneg"),
        CheckConstraint(
            "min_message_length >= 0",
            name="ck_guild_leveling_config_min_msg_len_nonneg",
        ),
    )

    guild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("guilds.id", ondelete="CASCADE"),
        primary_key=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    xp_min: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    xp_max: Mapped[int] = mapped_column(Integer, nullable=False, default=25)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    min_message_length: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    ignore_emoji_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ignore_link_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ignored_channel_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    ignored_role_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    notification_mode: Mapped[NotificationMode] = mapped_column(
        Enum(
            NotificationMode,
            name="notification_mode",
            values_callable=lambda x: [m.value for m in x],
        ),
        nullable=False,
        default=NotificationMode.CHANNEL,
    )
    notification_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    level_role_mode: Mapped[LevelRoleMode] = mapped_column(
        Enum(LevelRoleMode, name="level_role_mode", values_callable=lambda x: [m.value for m in x]),
        nullable=False,
        default=LevelRoleMode.REPLACING,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
