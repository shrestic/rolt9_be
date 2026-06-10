"""The `subscription` table — a RECURRING daily subscription (e.g. 'stock news at 8am').

Unlike `reminder` (one-shot): a subscription REPEATS every day and fetches FRESH content each
time (web search + AI summary). At HH:MM (Vietnam time), the scheduler posts to `channel_id`.
`last_run_on` = the most recent Vietnam-time run date, so it posts only once per day.
`active=False` (or deleted) when the user asks to stop. `topic` is free-text, so any subject
can be subscribed to (stocks, gold, weather, football...).
"""

import datetime
import uuid

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class Subscription(Base):
    __tablename__ = "subscription"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    creator_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Each subscription is one of two modes:
    #  - topic   != None: at fire time, SEARCH THE WEB + AI summary (a recurring bulletin, e.g. 'gold price').
    #  - message != None: at fire time, just PING that text (a repeating personal reminder, e.g. 'go home').
    topic: Mapped[str | None] = mapped_column(Text, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    hour: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # 0-23, Vietnam time to post each day
    minute: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    # Most recent Vietnam-time run date — so it posts only once per day (None = never run).
    last_run_on: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
