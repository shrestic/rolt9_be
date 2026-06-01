"""Data access cho `agent_message` — lịch sử hội thoại Claw Agent. Flush; commit ở boundary."""

import uuid
from datetime import datetime

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
    ) -> None:
        self.session.add(
            AgentMessage(
                guild_id=guild_id,
                conversation_id=conversation_id,
                role=role,
                content=content,
                discord_message_id=discord_message_id,
            )
        )
        await self.session.flush()

    async def recent_turns(
        self, conversation_id: uuid.UUID, *, limit: int, char_cap: int
    ) -> list[dict]:
        """N lượt mới nhất của cuộc, trả về thứ tự thời gian TĂNG dần, cắt theo char_cap."""
        r = await self.session.execute(
            select(AgentMessage)
            .where(AgentMessage.conversation_id == conversation_id)
            .order_by(desc(AgentMessage.id))
            .limit(limit)
        )
        rows = list(r.scalars().all())  # mới -> cũ
        out: list[dict] = []
        total = 0
        for row in rows:  # đi từ mới nhất, cộng tới khi vượt cap
            total += len(row.content)
            if total > char_cap and out:
                break
            out.append({"role": row.role, "content": row.content})
        out.reverse()  # về thứ tự tăng dần
        return out

    async def conversation_of(self, discord_message_id: int) -> uuid.UUID | None:
        r = await self.session.execute(
            select(AgentMessage.conversation_id).where(
                AgentMessage.discord_message_id == discord_message_id
            )
        )
        return r.scalar_one_or_none()

    async def delete_older_than(self, cutoff: datetime) -> int:
        """Xoá các lượt có created_at < cutoff (dọn rác định kỳ). Trả số dòng đã xoá."""
        res = await self.session.execute(
            delete(AgentMessage).where(AgentMessage.created_at < cutoff)
        )
        await self.session.flush()
        return res.rowcount or 0
