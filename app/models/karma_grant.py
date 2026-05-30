"""The `karma_grant` table — per giver→receiver cooldown ledger.

One row per (guild, giver, receiver) holding the last time that giver awarded
this receiver. The give-flow flips `last_granted_at` via a guarded atomic UPDATE
(see KarmaGrantRepository.try_grant) so a giver can only +1 the same person once
per cooldown window — blocking single-target spam.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class KarmaGrant(Base):
    __tablename__ = "karma_grant"
    __table_args__ = (
        UniqueConstraint("guild_id", "giver_id", "receiver_id", name="uq_karma_grant_pair"),
        Index("ix_karma_grant_guild", "guild_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    guild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False
    )
    giver_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    receiver_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
