"""Data access cho `agent_message` — lịch sử hội thoại Claw Agent. Flush; commit ở boundary."""

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
        """Cuộc gần nhất của đúng (guild, kênh, người) NẾU lượt cuối còn trong `within`.

        Dùng khi user nhắn tiếp mà KHÔNG reply: thay vì mở cuộc mới sạch trơn, ta nối
        lại cuộc vừa nói cho tự nhiên. Im lặng quá `within` -> trả None để mở cuộc mới.
        So thời gian ở Python (chuẩn hoá naive->UTC) để chạy đúng cả SQLite lẫn Postgres,
        không phụ thuộc số học datetime ở tầng DB.
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
        # SQLite trả naive (UTC ngầm), Postgres trả tz-aware -> chuẩn hoá về UTC rồi so.
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        if now - created_at > within:
            return None
        return conversation_id

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
