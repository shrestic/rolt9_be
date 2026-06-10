"""Data access for guild_wc_config (per-guild on/off + channel + shame nickname prefix)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guild_wc_config import GuildWCConfig


class WCConfigRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, guild_id: uuid.UUID) -> GuildWCConfig | None:
        return await self.session.get(GuildWCConfig, guild_id)

    async def get_or_create(self, guild_id: uuid.UUID) -> GuildWCConfig:
        row = await self.session.get(GuildWCConfig, guild_id)
        if row is None:
            row = GuildWCConfig(guild_id=guild_id)
            self.session.add(row)
            await self.session.flush()
        return row

    async def upsert(self, guild_id: uuid.UUID, data: dict) -> GuildWCConfig:
        row = await self.get_or_create(guild_id)
        for field, value in data.items():
            if hasattr(row, field):
                setattr(row, field, value)
        await self.session.flush()
        return row

    async def all_enabled(self) -> list[GuildWCConfig]:
        res = await self.session.execute(
            select(GuildWCConfig).where(
                GuildWCConfig.enabled.is_(True), GuildWCConfig.channel_id.isnot(None)
            )
        )
        return list(res.scalars().all())
