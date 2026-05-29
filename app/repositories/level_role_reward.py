import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.level_role_reward import LevelRoleReward


class LevelRoleRewardRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_guild(self, guild_id: uuid.UUID) -> list[LevelRoleReward]:
        r = await self.session.execute(
            select(LevelRoleReward)
            .where(LevelRoleReward.guild_id == guild_id)
            .order_by(LevelRoleReward.level.asc())
        )
        return list(r.scalars().all())

    async def upsert(self, guild_id: uuid.UUID, *, level: int, role_id: int) -> LevelRoleReward:
        existing = await self.session.execute(
            select(LevelRoleReward).where(
                LevelRoleReward.guild_id == guild_id, LevelRoleReward.level == level
            )
        )
        row = existing.scalar_one_or_none()
        if row is None:
            row = LevelRoleReward(guild_id=guild_id, level=level, role_id=role_id)
            self.session.add(row)
        else:
            row.role_id = role_id
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def delete_by_level(self, guild_id: uuid.UUID, level: int) -> bool:
        r = await self.session.execute(
            delete(LevelRoleReward).where(
                LevelRoleReward.guild_id == guild_id, LevelRoleReward.level == level
            )
        )
        await self.session.flush()
        return r.rowcount > 0

    async def delete_by_role(self, guild_id: uuid.UUID, role_id: int) -> int:
        r = await self.session.execute(
            delete(LevelRoleReward).where(
                LevelRoleReward.guild_id == guild_id, LevelRoleReward.role_id == role_id
            )
        )
        await self.session.flush()
        return int(r.rowcount or 0)
