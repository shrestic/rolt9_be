"""Data access cho bảng `reminder` (nhắc hẹn).

`due` lấy các lời nhắc tới giờ & chưa bắn (scheduler gọi mỗi phút). `create` ghi lời nhắc
mới (remind_at đã là UTC). Commit ở boundary (session_scope) — repo chỉ flush.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reminder import Reminder


class ReminderRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        guild_id: uuid.UUID,
        channel_id: int,
        creator_id: int,
        target_ids: list[int],
        message: str,
        remind_at: datetime,
    ) -> Reminder:
        row = Reminder(
            guild_id=guild_id,
            channel_id=channel_id,
            creator_id=creator_id,
            target_ids=list(target_ids),
            message=message,
            remind_at=remind_at,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def due(self, now: datetime, limit: int = 50) -> list[Reminder]:
        """Các lời nhắc đã tới giờ (remind_at <= now) và chưa bắn — cũ nhất trước."""
        res = await self.session.execute(
            select(Reminder)
            .where(Reminder.fired.is_(False), Reminder.remind_at <= now)
            .order_by(Reminder.remind_at)
            .limit(limit)
        )
        return list(res.scalars().all())

    async def mark_fired(self, reminder_id: int) -> None:
        row = await self.session.get(Reminder, reminder_id)
        if row is not None:
            row.fired = True
        await self.session.flush()

    async def pending_for_guild(self, guild_id: uuid.UUID) -> list[Reminder]:
        """Các lời nhắc còn chờ của 1 server (để hiện danh sách / huỷ)."""
        res = await self.session.execute(
            select(Reminder)
            .where(Reminder.guild_id == guild_id, Reminder.fired.is_(False))
            .order_by(Reminder.remind_at)
        )
        return list(res.scalars().all())

    async def cancel(self, reminder_id: int, guild_id: uuid.UUID) -> bool:
        """Huỷ 1 lời nhắc còn chờ của server. Trả True nếu huỷ được."""
        row = await self.session.get(Reminder, reminder_id)
        if row is not None and row.guild_id == guild_id and not row.fired:
            await self.session.delete(row)
            await self.session.flush()
            return True
        return False

    async def update_reminder(
        self,
        reminder_id: int,
        guild_id: uuid.UUID,
        *,
        remind_at: datetime | None = None,
        message: str | None = None,
    ) -> Reminder | None:
        """Sửa giờ và/hoặc nội dung 1 lời nhắc còn chờ. Chỉ đổi field được truyền. Trả row đã sửa."""
        row = await self.session.get(Reminder, reminder_id)
        if row is None or row.guild_id != guild_id or row.fired:
            return None
        if remind_at is not None:
            row.remind_at = remind_at
        if message is not None:
            row.message = message
        await self.session.flush()
        return row
