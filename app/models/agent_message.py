"""The `agent_message` table — short-term conversation history of the Claw Agent.

Each row is one turn (user or assistant), grouped by `conversation_id`. Assistant
turns store `discord_message_id` so that when a user replies to a bot message, we can
trace back to the conversation to continue it. PK `id` is an autoincrement integer →
deterministic insertion order (NOT based on created_at, because within a single
Postgres transaction every now() is equal). Only the N most recent turns are loaded
into the prompt; old rows remain (not cleaned up yet).

`channel_id` + `user_discord_id` are attached to EVERY turn of the conversation
(including assistant turns, which carry the channel/person the bot is replying to).
This way, when a user sends another message WITHOUT replying, we can still look up
"the most recent conversation of (channel, person) within X minutes" to continue
naturally (see `AgentMessageRepository.latest_conversation`). Both are nullable for
compatibility with old rows.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class AgentMessage(Base):
    __tablename__ = "agent_message"
    __table_args__ = (
        CheckConstraint("role in ('user','assistant')", name="ck_agent_message_role"),
        # Look up "the most recent conversation of (channel, person)" — filter by 3 columns, order by id descending.
        Index(
            "ix_agent_message_guild_channel_user",
            "guild_id",
            "channel_id",
            "user_discord_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    discord_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    # Channel + person of the conversation — to continue the most recent conversation when the user doesn't reply (window-based).
    channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    user_discord_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
