"""Data access cho `subscription` (đăng ký nhận tin định kỳ). Flush; commit ở boundary."""

import datetime
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import Subscription

_UNSET = object()  # phân biệt 'không sửa' với 'sửa thành None' (vd reset last_run_on)


class SubscriptionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        guild_id: uuid.UUID,
        channel_id: int,
        creator_id: int,
        topic: str,
        hour: int,
        minute: int,
        last_run_on: datetime.date | None = None,
    ) -> Subscription:
        row = Subscription(
            guild_id=guild_id,
            channel_id=channel_id,
            creator_id=creator_id,
            topic=topic,
            hour=hour,
            minute=minute,
            last_run_on=last_run_on,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def active_all(self) -> list[Subscription]:
        """Mọi đăng ký đang bật (mọi guild) — scheduler lọc 'tới giờ' trong Python."""
        res = await self.session.execute(select(Subscription).where(Subscription.active.is_(True)))
        return list(res.scalars().all())

    async def active_for_creator(self, guild_id: uuid.UUID, creator_id: int) -> list[Subscription]:
        """Đăng ký đang bật CỦA một người trong 1 guild (để liệt kê / huỷ)."""
        res = await self.session.execute(
            select(Subscription)
            .where(
                Subscription.guild_id == guild_id,
                Subscription.creator_id == creator_id,
                Subscription.active.is_(True),
            )
            .order_by(Subscription.hour, Subscription.minute)
        )
        return list(res.scalars().all())

    async def mark_ran(self, sub_id: int, on_date: datetime.date) -> None:
        row = await self.session.get(Subscription, sub_id)
        if row is not None:
            row.last_run_on = on_date
        await self.session.flush()

    async def cancel(self, sub_id: int, guild_id: uuid.UUID) -> bool:
        """Huỷ (xoá) 1 đăng ký của guild. Trả True nếu xoá được."""
        row = await self.session.get(Subscription, sub_id)
        if row is not None and row.guild_id == guild_id:
            await self.session.delete(row)
            await self.session.flush()
            return True
        return False

    async def update(
        self,
        sub_id: int,
        guild_id: uuid.UUID,
        *,
        hour: int | None = None,
        minute: int | None = None,
        topic: str | None = None,
        last_run_on=_UNSET,
    ) -> Subscription | None:
        """Sửa giờ và/hoặc chủ đề 1 đăng ký. Chỉ đổi field được truyền. `last_run_on` dùng sentinel
        nên truyền None là RESET (để lịch mới có hiệu lực). Trả row đã sửa."""
        row = await self.session.get(Subscription, sub_id)
        if row is None or row.guild_id != guild_id:
            return None
        if hour is not None:
            row.hour = hour
        if minute is not None:
            row.minute = minute
        if topic is not None:
            row.topic = topic
        if last_run_on is not _UNSET:
            row.last_run_on = last_run_on
        await self.session.flush()
        return row
