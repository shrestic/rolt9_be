"""Data access cho `guild_user_memory` — facts dài hạn per-user-per-guild.

No-404 pattern: get trả "" nếu chưa có. Flush; commit ở boundary.
"""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guild_user_memory import GuildUserMemory


class UserMemoryRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_facts(self, guild_id: uuid.UUID, user_discord_id: int) -> str:
        r = await self.session.execute(
            select(GuildUserMemory.facts).where(
                GuildUserMemory.guild_id == guild_id,
                GuildUserMemory.user_discord_id == user_discord_id,
            )
        )
        return r.scalar_one_or_none() or ""

    async def upsert_facts(self, guild_id: uuid.UUID, user_discord_id: int, facts: str) -> None:
        r = await self.session.execute(
            select(GuildUserMemory).where(
                GuildUserMemory.guild_id == guild_id,
                GuildUserMemory.user_discord_id == user_discord_id,
            )
        )
        row = r.scalar_one_or_none()
        if row is None:
            self.session.add(
                GuildUserMemory(guild_id=guild_id, user_discord_id=user_discord_id, facts=facts)
            )
        else:
            row.facts = facts
        await self.session.flush()

    async def clear(self, guild_id: uuid.UUID, user_discord_id: int) -> None:
        await self.session.execute(
            delete(GuildUserMemory).where(
                GuildUserMemory.guild_id == guild_id,
                GuildUserMemory.user_discord_id == user_discord_id,
            )
        )
        await self.session.flush()
