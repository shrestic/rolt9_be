import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guild_rank_card_theme import GuildRankCardTheme


class GuildRankCardThemeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, guild_id: uuid.UUID) -> GuildRankCardTheme | None:
        r = await self.session.execute(
            select(GuildRankCardTheme).where(GuildRankCardTheme.guild_id == guild_id)
        )
        return r.scalar_one_or_none()

    async def get_or_create(self, guild_id: uuid.UUID) -> GuildRankCardTheme:
        existing = await self.get(guild_id)
        if existing is not None:
            return existing
        t = GuildRankCardTheme(guild_id=guild_id)
        self.session.add(t)
        await self.session.flush()
        await self.session.refresh(t)
        return t

    async def upsert(self, guild_id: uuid.UUID, data: dict) -> GuildRankCardTheme:
        t = await self.get_or_create(guild_id)
        for field, value in data.items():
            if hasattr(t, field):
                setattr(t, field, value)
        await self.session.flush()
        await self.session.refresh(t)
        return t
