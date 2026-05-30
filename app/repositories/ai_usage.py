"""Data access for `ai_usage` — monthly Claude token counters per guild.

`add_tokens` uses the wallet-style atomic increment (`tokens = tokens + n` in SQL)
so concurrent AI calls don't lose usage. Flush only; commit at the boundary.
"""

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_usage import AIUsage


class AIUsageRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def tokens_this_period(self, guild_id: uuid.UUID, period_key: str) -> int:
        """Tokens spent by the guild in `period_key` (0 if no row yet)."""
        r = await self.session.execute(
            select(AIUsage.tokens).where(
                AIUsage.guild_id == guild_id, AIUsage.period_key == period_key
            )
        )
        row = r.scalar_one_or_none()
        return int(row) if row is not None else 0

    async def _get_or_create(self, guild_id: uuid.UUID, period_key: str) -> AIUsage:
        r = await self.session.execute(
            select(AIUsage).where(AIUsage.guild_id == guild_id, AIUsage.period_key == period_key)
        )
        row = r.scalar_one_or_none()
        if row is not None:
            return row
        row = AIUsage(guild_id=guild_id, period_key=period_key, tokens=0)
        self.session.add(row)
        await self.session.flush()
        return row

    async def add_tokens(self, guild_id: uuid.UUID, period_key: str, n: int) -> None:
        """Add `n` tokens to the month's usage (atomic SQL increment)."""
        await self._get_or_create(guild_id, period_key)
        stmt = (
            update(AIUsage)
            .where(AIUsage.guild_id == guild_id, AIUsage.period_key == period_key)
            .values(tokens=AIUsage.tokens + n)
            .execution_options(synchronize_session="fetch")
        )
        await self.session.execute(stmt)
        await self.session.flush()
