"""Data access for `guild_ai_config` — AI on/off + monthly token budget.

"No 404 / get_or_create defaults" pattern, like CurrencyConfigRepository. Flush
only; the caller's session scope owns the commit.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guild_ai_config import GuildAIConfig


class AIConfigRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, guild_id: uuid.UUID) -> GuildAIConfig | None:
        r = await self.session.execute(
            select(GuildAIConfig).where(GuildAIConfig.guild_id == guild_id)
        )
        return r.scalar_one_or_none()

    async def get_or_create(self, guild_id: uuid.UUID) -> GuildAIConfig:
        existing = await self.get(guild_id)
        if existing is not None:
            return existing
        cfg = GuildAIConfig(guild_id=guild_id)
        self.session.add(cfg)
        await self.session.flush()
        await self.session.refresh(cfg)
        return cfg

    async def upsert(self, guild_id: uuid.UUID, data: dict) -> GuildAIConfig:
        cfg = await self.get_or_create(guild_id)
        for field, value in data.items():
            if hasattr(cfg, field):
                setattr(cfg, field, value)
        await self.session.flush()
        await self.session.refresh(cfg)
        return cfg
