from collections.abc import Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guild import Guild


class GuildRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_discord_id(self, discord_id: int) -> Guild | None:
        r = await self.session.execute(select(Guild).where(Guild.discord_id == discord_id))
        return r.scalar_one_or_none()

    async def get_active_by_discord_ids(self, discord_ids: Sequence[int]) -> list[Guild]:
        if not discord_ids:
            return []
        r = await self.session.execute(
            select(Guild).where(Guild.discord_id.in_(discord_ids), Guild.is_active.is_(True))
        )
        return list(r.scalars().all())

    async def upsert(self, *, discord_id: int, name: str, icon_url: str | None) -> Guild:
        existing = await self.get_by_discord_id(discord_id)
        if existing is None:
            g = Guild(discord_id=discord_id, name=name, icon_url=icon_url, is_active=True)
            self.session.add(g)
            await self.session.flush()
            await self.session.refresh(g)
            return g
        existing.name = name
        existing.icon_url = icon_url
        existing.is_active = True
        await self.session.flush()
        await self.session.refresh(existing)
        return existing

    async def mark_inactive(self, discord_id: int) -> None:
        await self.session.execute(
            update(Guild).where(Guild.discord_id == discord_id).values(is_active=False)
        )
        await self.session.flush()
