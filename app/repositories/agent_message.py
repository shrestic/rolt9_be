"""Data access for `agent_message` — Claw Agent conversation history. Flush; commit at boundary."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_message import AgentMessage


class AgentMessageRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add_turn(
        self,
        guild_id: uuid.UUID,
        conversation_id: uuid.UUID,
        role: str,
        content: str,
        discord_message_id: int | None = None,
        channel_id: int | None = None,
        user_discord_id: int | None = None,
    ) -> None:
        self.session.add(
            AgentMessage(
                guild_id=guild_id,
                conversation_id=conversation_id,
                role=role,
                content=content,
                discord_message_id=discord_message_id,
                channel_id=channel_id,
                user_discord_id=user_discord_id,
            )
        )
        await self.session.flush()

    async def latest_conversation(
        self,
        guild_id: uuid.UUID,
        *,
        channel_id: int,
        user_discord_id: int,
        within: timedelta,
        now: datetime,
    ) -> uuid.UUID | None:
        """Most recent conversation of the exact (guild, channel, person) IF the last turn is still within `within`.

        Used when the user sends another message WITHOUT replying: instead of opening a
        brand-new conversation, we reattach to the one they were just having, which feels
        natural. Silent for longer than `within` -> return None to open a new conversation.
        Compare time in Python (normalize naive->UTC) so it works on both SQLite and Postgres,
        not depending on datetime arithmetic at the DB layer.
        """
        r = await self.session.execute(
            select(AgentMessage.conversation_id, AgentMessage.created_at)
            .where(
                AgentMessage.guild_id == guild_id,
                AgentMessage.channel_id == channel_id,
                AgentMessage.user_discord_id == user_discord_id,
            )
            .order_by(desc(AgentMessage.id))
            .limit(1)
        )
        row = r.first()
        if row is None:
            return None
        conversation_id, created_at = row
        if created_at is None:
            return None
        # SQLite returns naive (implicitly UTC), Postgres returns tz-aware -> normalize to UTC then compare.
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        if now - created_at > within:
            return None
        return conversation_id

    async def recent_turns(
        self, conversation_id: uuid.UUID, *, limit: int, char_cap: int
    ) -> list[dict]:
        """The N most recent turns of the conversation, returned in ASCENDING time order, capped by char_cap."""
        r = await self.session.execute(
            select(AgentMessage)
            .where(AgentMessage.conversation_id == conversation_id)
            .order_by(desc(AgentMessage.id))
            .limit(limit)
        )
        rows = list(r.scalars().all())  # newest -> oldest
        out: list[dict] = []
        total = 0
        for row in rows:  # walk from newest, accumulate until over cap
            total += len(row.content)
            if total > char_cap and out:
                break
            out.append({"role": row.role, "content": row.content})
        out.reverse()  # back to ascending order
        return out

    async def conversation_of(self, discord_message_id: int) -> uuid.UUID | None:
        r = await self.session.execute(
            select(AgentMessage.conversation_id).where(
                AgentMessage.discord_message_id == discord_message_id
            )
        )
        return r.scalar_one_or_none()

    async def delete_older_than(self, cutoff: datetime) -> int:
        """Delete turns with created_at < cutoff (periodic cleanup). Returns the number of rows deleted."""
        res = await self.session.execute(
            delete(AgentMessage).where(AgentMessage.created_at < cutoff)
        )
        await self.session.flush()
        return res.rowcount or 0
