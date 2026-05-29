import uuid
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_xp import UserXp


class UserXpRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, guild_id: uuid.UUID, user_id: int) -> UserXp | None:
        r = await self.session.execute(
            select(UserXp).where(UserXp.guild_id == guild_id, UserXp.user_id == user_id)
        )
        return r.scalar_one_or_none()

    async def get_or_create(self, guild_id: uuid.UUID, user_id: int) -> UserXp:
        existing = await self.get(guild_id, user_id)
        if existing is not None:
            return existing
        row = UserXp(guild_id=guild_id, user_id=user_id, total_xp=0)
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def set_xp(
        self,
        guild_id: uuid.UUID,
        user_id: int,
        total_xp: int,
        last_xp_at: datetime | None = None,
    ) -> UserXp:
        row = await self.get_or_create(guild_id, user_id)
        row.total_xp = total_xp
        if last_xp_at is not None:
            row.last_xp_at = last_xp_at
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def delete(self, guild_id: uuid.UUID, user_id: int) -> bool:
        r = await self.session.execute(
            delete(UserXp).where(UserXp.guild_id == guild_id, UserXp.user_id == user_id)
        )
        await self.session.flush()
        return r.rowcount > 0

    async def leaderboard(
        self, guild_id: uuid.UUID, *, limit: int = 20, offset: int = 0
    ) -> tuple[list[UserXp], int]:
        total_r = await self.session.execute(
            select(func.count()).select_from(UserXp).where(UserXp.guild_id == guild_id)
        )
        total = int(total_r.scalar_one())
        r = await self.session.execute(
            select(UserXp)
            .where(UserXp.guild_id == guild_id)
            .order_by(UserXp.total_xp.desc(), UserXp.user_id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(r.scalars().all()), total

    async def rank_of(self, guild_id: uuid.UUID, user_id: int) -> int | None:
        # 1-indexed rank by total_xp DESC. Returns None if the user has no row.
        target = await self.get(guild_id, user_id)
        if target is None:
            return None
        r = await self.session.execute(
            select(func.count())
            .select_from(UserXp)
            .where(UserXp.guild_id == guild_id, UserXp.total_xp > target.total_xp)
        )
        ahead = int(r.scalar_one())
        return ahead + 1
