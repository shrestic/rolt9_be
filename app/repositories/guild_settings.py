import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guild_settings import GuildSettings


class GuildSettingsRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, guild_id: uuid.UUID) -> GuildSettings | None:
        r = await self.session.execute(
            select(GuildSettings).where(GuildSettings.guild_id == guild_id)
        )
        return r.scalar_one_or_none()

    async def create_defaults(self, guild_id: uuid.UUID) -> GuildSettings:
        existing = await self.get(guild_id)
        if existing is not None:
            return existing
        s = GuildSettings(
            guild_id=guild_id,
            moderation={},
            welcome={},
            automod={},
            logging={},
            leveling={},
        )
        self.session.add(s)
        await self.session.commit()
        await self.session.refresh(s)
        return s
