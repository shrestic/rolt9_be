"""Data access cho `ai_usage` — đếm token + chi phí USD per-guild theo tháng.

`add_usage` dùng increment atomic kiểu ví (`tokens = tokens + n`, `cost_usd =
cost_usd + c` trong SQL) để các call AI song song không mất số liệu. Chỉ flush;
commit ở boundary.
"""

import uuid
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_usage import AIUsage


class AIUsageRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def tokens_this_period(self, guild_id: uuid.UUID, period_key: str) -> int:
        """Token đã dùng trong `period_key` (0 nếu chưa có row)."""
        r = await self.session.execute(
            select(AIUsage.tokens).where(
                AIUsage.guild_id == guild_id, AIUsage.period_key == period_key
            )
        )
        row = r.scalar_one_or_none()
        return int(row) if row is not None else 0

    async def cost_this_period(self, guild_id: uuid.UUID, period_key: str) -> Decimal:
        """Chi phí USD đã dùng trong `period_key` (Decimal('0') nếu chưa có row)."""
        r = await self.session.execute(
            select(AIUsage.cost_usd).where(
                AIUsage.guild_id == guild_id, AIUsage.period_key == period_key
            )
        )
        row = r.scalar_one_or_none()
        return Decimal(row) if row is not None else Decimal("0")

    async def _get_or_create(self, guild_id: uuid.UUID, period_key: str) -> AIUsage:
        r = await self.session.execute(
            select(AIUsage).where(AIUsage.guild_id == guild_id, AIUsage.period_key == period_key)
        )
        row = r.scalar_one_or_none()
        if row is not None:
            return row
        row = AIUsage(guild_id=guild_id, period_key=period_key, tokens=0, cost_usd=0)
        self.session.add(row)
        await self.session.flush()
        return row

    async def add_usage(
        self, guild_id: uuid.UUID, period_key: str, *, tokens: int, cost_usd: float
    ) -> None:
        """Cộng dồn token + chi phí USD vào usage của tháng (increment atomic)."""
        await self._get_or_create(guild_id, period_key)
        stmt = (
            update(AIUsage)
            .where(AIUsage.guild_id == guild_id, AIUsage.period_key == period_key)
            .values(tokens=AIUsage.tokens + tokens, cost_usd=AIUsage.cost_usd + cost_usd)
            .execution_options(synchronize_session="fetch")
        )
        await self.session.execute(stmt)
        await self.session.flush()
