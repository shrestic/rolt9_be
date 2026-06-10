"""The `reminder` table — pre-scheduled reminders.

Each row is one reminder: at `remind_at` (stored UTC), the scheduler posts to `channel_id`
and @pings the people in `target_ids`. Stored in the DB (NOT AI memory), so it survives
restarts and still fires correctly weeks/months later. `fired` marks it as already sent so
it doesn't repeat. `target_ids` is a JSON list of Discord user ids (numbers) to tag.
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class Reminder(Base):
    __tablename__ = "reminder"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    creator_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # List of user ids (numbers) to @ping when the time comes. JSON for compactness (portable SQLite + PG).
    target_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # Smart reminder: if set, at fire time the bot does a live LOOKUP (web_search) + a real AI answer for `task`
    # (e.g. 'today's gold price') instead of just echoing `message`. NULL = a regular reminder.
    task: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Reminder time — STORED UTC (tz-aware). Indexed for fast "which ones are due" queries.
    remind_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    fired: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
