"""Data access for `guild_welcome_config` — welcome/leave plugin settings.

"No 404 / get_or_create defaults" pattern. Flush only; commit at the boundary.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guild_welcome_config import GuildWelcomeConfig


class WelcomeConfigRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, guild_id: uuid.UUID) -> GuildWelcomeConfig | None:
        r = await self.session.execute(
            select(GuildWelcomeConfig).where(GuildWelcomeConfig.guild_id == guild_id)
        )
        return r.scalar_one_or_none()

    async def get_or_create(self, guild_id: uuid.UUID) -> GuildWelcomeConfig:
        existing = await self.get(guild_id)
        if existing is not None:
            return existing
        cfg = GuildWelcomeConfig(guild_id=guild_id)
        self.session.add(cfg)
        await self.session.flush()
        await self.session.refresh(cfg)
        return cfg

    async def upsert(self, guild_id: uuid.UUID, data: dict) -> GuildWelcomeConfig:
        cfg = await self.get_or_create(guild_id)
        for field, value in data.items():
            if hasattr(cfg, field):
                setattr(cfg, field, value)
        await self.session.flush()
        await self.session.refresh(cfg)
        return cfg
