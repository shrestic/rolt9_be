"""Data access for `guild_minigame_config` — per-guild mini-games settings.

Same "no 404 / get_or_create defaults" pattern as CurrencyConfigRepository.
Flush only; commit at the boundary.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guild_minigame_config import GuildMinigameConfig


class MinigameConfigRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, guild_id: uuid.UUID) -> GuildMinigameConfig | None:
        r = await self.session.execute(
            select(GuildMinigameConfig).where(GuildMinigameConfig.guild_id == guild_id)
        )
        return r.scalar_one_or_none()

    async def get_or_create(self, guild_id: uuid.UUID) -> GuildMinigameConfig:
        existing = await self.get(guild_id)
        if existing is not None:
            return existing
        cfg = GuildMinigameConfig(guild_id=guild_id)
        self.session.add(cfg)
        await self.session.flush()
        await self.session.refresh(cfg)
        return cfg

    async def upsert(self, guild_id: uuid.UUID, data: dict) -> GuildMinigameConfig:
        cfg = await self.get_or_create(guild_id)
        for field, value in data.items():
            if hasattr(cfg, field):
                setattr(cfg, field, value)
        await self.session.flush()
        await self.session.refresh(cfg)
        return cfg
