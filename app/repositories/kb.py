"""Data access for `guild_kb_entry` — admin knowledge entries for `/ask`.

Plain CRUD. Flush only; commit at the boundary.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guild_kb_entry import GuildKbEntry


class KbRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_for_guild(self, guild_id: uuid.UUID) -> list[GuildKbEntry]:
        r = await self.session.execute(
            select(GuildKbEntry)
            .where(GuildKbEntry.guild_id == guild_id)
            .order_by(GuildKbEntry.created_at.asc())
        )
        return list(r.scalars().all())

    async def get(self, guild_id: uuid.UUID, entry_id: uuid.UUID) -> GuildKbEntry | None:
        r = await self.session.execute(
            select(GuildKbEntry).where(
                GuildKbEntry.guild_id == guild_id, GuildKbEntry.id == entry_id
            )
        )
        return r.scalar_one_or_none()

    async def create(self, guild_id: uuid.UUID, *, title: str, content: str) -> GuildKbEntry:
        entry = GuildKbEntry(guild_id=guild_id, title=title, content=content)
        self.session.add(entry)
        await self.session.flush()
        await self.session.refresh(entry)
        return entry

    async def delete(self, entry: GuildKbEntry) -> None:
        await self.session.delete(entry)
        await self.session.flush()
