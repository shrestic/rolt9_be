"""Data access for the `reminder` table (reminders).

`due` fetches reminders that are due & not yet fired (scheduler calls every minute). `create` writes a
new reminder (remind_at is already UTC). Commit at boundary (session_scope) — the repo only flushes.
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
        task: str | None = None,
    ) -> Reminder:
        row = Reminder(
            guild_id=guild_id,
            channel_id=channel_id,
            creator_id=creator_id,
            target_ids=list(target_ids),
            message=message,
            remind_at=remind_at,
            task=task,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def due(self, now: datetime, limit: int = 50) -> list[Reminder]:
        """Reminders that are due (remind_at <= now) and not yet fired — oldest first."""
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
        """Pending reminders of a server (to list / cancel)."""
        res = await self.session.execute(
            select(Reminder)
            .where(Reminder.guild_id == guild_id, Reminder.fired.is_(False))
            .order_by(Reminder.remind_at)
        )
        return list(res.scalars().all())

    async def cancel(self, reminder_id: int, guild_id: uuid.UUID) -> bool:
        """Cancel a pending reminder of the server. Returns True if it was cancelled."""
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
        """Edit the time and/or content of a pending reminder. Only changes the fields passed. Returns the edited row."""
        row = await self.session.get(Reminder, reminder_id)
        if row is None or row.guild_id != guild_id or row.fired:
            return None
        if remind_at is not None:
            row.remind_at = remind_at
        if message is not None:
            row.message = message
        await self.session.flush()
        return row
