import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mod_case import ModCase


class ModCaseRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _next_case_number(self, guild_id: uuid.UUID) -> int:
        r = await self.session.execute(
            select(func.coalesce(func.max(ModCase.case_number), 0)).where(
                ModCase.guild_id == guild_id
            )
        )
        return int(r.scalar_one()) + 1

    async def create_case(
        self,
        *,
        guild_id: uuid.UUID,
        action: str,
        source: str = "manual",
        target_user_id: int,
        target_username: str,
        moderator_user_id: int,
        moderator_username: str,
        reason: str | None = None,
        duration_seconds: int | None = None,
        expires_at: datetime | None = None,
    ) -> ModCase:
        case = ModCase(
            guild_id=guild_id,
            case_number=await self._next_case_number(guild_id),
            action=action,
            source=source,
            target_user_id=target_user_id,
            target_username=target_username,
            moderator_user_id=moderator_user_id,
            moderator_username=moderator_username,
            reason=reason,
            duration_seconds=duration_seconds,
            expires_at=expires_at,
            active=True,
        )
        self.session.add(case)
        await self.session.commit()
        await self.session.refresh(case)
        return case

    async def active_warn_count(self, guild_id: uuid.UUID, target_user_id: int) -> int:
        r = await self.session.execute(
            select(func.count())
            .select_from(ModCase)
            .where(
                ModCase.guild_id == guild_id,
                ModCase.target_user_id == target_user_id,
                ModCase.action == "warn",
                ModCase.active.is_(True),
            )
        )
        return int(r.scalar_one())

    async def list_cases(
        self,
        *,
        guild_id: uuid.UUID,
        target_user_id: int | None = None,
        action: str | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[ModCase], int]:
        conditions = [ModCase.guild_id == guild_id]
        if target_user_id is not None:
            conditions.append(ModCase.target_user_id == target_user_id)
        if action is not None:
            conditions.append(ModCase.action == action)

        total_r = await self.session.execute(
            select(func.count()).select_from(ModCase).where(*conditions)
        )
        total = int(total_r.scalar_one())

        r = await self.session.execute(
            select(ModCase)
            .where(*conditions)
            .order_by(ModCase.case_number.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(r.scalars().all()), total

    async def get_by_case_number(self, guild_id: uuid.UUID, case_number: int) -> ModCase | None:
        r = await self.session.execute(
            select(ModCase).where(ModCase.guild_id == guild_id, ModCase.case_number == case_number)
        )
        return r.scalar_one_or_none()

    async def deactivate(self, case: ModCase) -> ModCase:
        case.active = False
        await self.session.commit()
        await self.session.refresh(case)
        return case
