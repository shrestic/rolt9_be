"""The `guild_pet` table — one shared pet per guild (live state + config in one row).

One row per guild (PK = guild_id), holding both the pet's live state (hunger,
happiness, xp, last_decay_at) and the admin-tunable config (enabled, name, costs,
decay rate). Like leveling/currency, the pet is off by default. `last_decay_at`
anchors the lazy time-decay (see pet_logic.settle_decay).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class GuildPet(Base):
    __tablename__ = "guild_pet"
    __table_args__ = (
        CheckConstraint("hunger >= 0 AND hunger <= 100", name="ck_pet_hunger_range"),
        CheckConstraint("happiness >= 0 AND happiness <= 100", name="ck_pet_happiness_range"),
        CheckConstraint("xp >= 0", name="ck_pet_xp_nonneg"),
        CheckConstraint("feed_cost >= 0", name="ck_pet_feed_cost_nonneg"),
        CheckConstraint("feed_amount >= 0", name="ck_pet_feed_amount_nonneg"),
        CheckConstraint("play_amount >= 0", name="ck_pet_play_amount_nonneg"),
        CheckConstraint("decay_per_day >= 0", name="ck_pet_decay_nonneg"),
    )

    guild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True
    )
    # Whether the pet feature is enabled for this guild (off by default, admin enables via /pet config).
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Display name of the pet, customisable by admins (e.g. "Rolt", "Doggo").
    name: Mapped[str] = mapped_column(String(32), nullable=False, default="Pet")
    # Live state — hunger drains over time; feeding restores it.
    hunger: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    # Live state — happiness drains over time; playing restores it.
    happiness: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    # Accumulated XP — increases when fed or played with; used to derive pet level.
    xp: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Timestamp of the most-recent decay tick; NULL = pet was just created / never decayed.
    # pet_logic.settle_decay computes elapsed days since this timestamp and
    # subtracts (elapsed * decay_per_day) from hunger + happiness atomically.
    last_decay_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Config — how many currency units members spend when feeding the pet.
    feed_cost: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    # Config — how many hunger points a single /pet feed restores.
    feed_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    # Config — how many happiness points a single /pet play restores.
    play_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    # Config — how many stat points (hunger + happiness) decay per 24-hour period of neglect.
    decay_per_day: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
