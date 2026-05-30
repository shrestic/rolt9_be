"""Data access for `guild_quest` — admin-defined quest templates.

Plain CRUD plus `list_enabled` (used both by the `/quests` view and the
progress-recording hot path, where it's filtered by objective_type and backed by
the `(guild_id, enabled)` index). Flush only; the caller's session scope commits.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guild_quest import GuildQuest


class QuestRepository:
    def __init__(self, session: AsyncSession):
        # Hold the async session injected by the caller (FastAPI dependency or
        # session_scope).  All methods share this session so they participate in
        # the same Unit-of-Work transaction.
        self.session = session

    async def list_for_guild(self, guild_id: uuid.UUID) -> list[GuildQuest]:
        """All quests of a guild (enabled or not), newest first — for the dashboard."""
        r = await self.session.execute(
            select(GuildQuest)
            .where(GuildQuest.guild_id == guild_id)
            .order_by(GuildQuest.created_at.desc())
        )
        return list(r.scalars().all())

    async def list_enabled(
        self, guild_id: uuid.UUID, objective_type: str | None = None
    ) -> list[GuildQuest]:
        """Enabled quests, optionally filtered to one objective_type.

        This is the hot path for the progress-recording service: it hits the
        `(guild_id, enabled)` composite index on `guild_quest` to stay fast even
        when a guild has many defined quests.
        """
        stmt = select(GuildQuest).where(
            GuildQuest.guild_id == guild_id, GuildQuest.enabled.is_(True)
        )
        if objective_type is not None:
            # Narrow further to a specific objective, e.g. "earn_coins" or
            # "daily_claim", so the caller only processes relevant quests.
            stmt = stmt.where(GuildQuest.objective_type == objective_type)
        r = await self.session.execute(stmt)
        return list(r.scalars().all())

    async def get(self, guild_id: uuid.UUID, quest_id: uuid.UUID) -> GuildQuest | None:
        """Fetch a single quest by guild + quest PK, or None if not found."""
        r = await self.session.execute(
            select(GuildQuest).where(GuildQuest.guild_id == guild_id, GuildQuest.id == quest_id)
        )
        return r.scalar_one_or_none()

    async def create(self, guild_id: uuid.UUID, data: dict) -> GuildQuest:
        """Insert a new quest row and return it with all server-side defaults populated.

        `data` must contain at minimum: name, period, objective_type, target.
        Optional fields (description, reward_coins, enabled) fall back to their
        model-level defaults if absent.
        """
        quest = GuildQuest(guild_id=guild_id, **data)
        self.session.add(quest)
        await self.session.flush()  # sends INSERT, materialises UUID PK
        await self.session.refresh(quest)  # reloads created_at / updated_at
        return quest

    async def update(self, quest: GuildQuest, data: dict) -> GuildQuest:
        """Apply a partial field update to an already-loaded quest instance.

        Unknown keys in `data` are silently skipped (same defensive pattern as
        CurrencyConfigRepository.upsert) so callers don't need to pre-filter.
        """
        for field, value in data.items():
            # Only touch attributes that actually exist on the model.
            if hasattr(quest, field):
                setattr(quest, field, value)
        await self.session.flush()
        await self.session.refresh(quest)  # pick up any server-side updated_at
        return quest

    async def delete(self, quest: GuildQuest) -> None:
        """Remove a quest row.  The caller's session scope will commit the DELETE."""
        await self.session.delete(quest)
        await self.session.flush()
