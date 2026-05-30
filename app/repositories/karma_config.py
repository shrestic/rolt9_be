"""Data access for `guild_karma_config` — the per-guild karma on/off switch.

Same "no 404 / get_or_create defaults" pattern as CurrencyConfigRepository.
Flush only; commit at the boundary.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guild_karma_config import GuildKarmaConfig


class KarmaConfigRepository:
    """Repository for reading and mutating a guild's karma configuration.

    There is at most one `GuildKarmaConfig` row per guild (guild_id is the
    primary key), so the interface is simple: get, get_or_create, upsert. No
    pagination or bulk operations are needed.
    """

    def __init__(self, session: AsyncSession):
        # Shared async session; all methods join the same Unit-of-Work transaction.
        self.session = session

    async def get(self, guild_id: uuid.UUID) -> GuildKarmaConfig | None:
        """Return the config row for `guild_id`, or None if it doesn't exist yet.

        Used internally by `get_or_create` and `upsert`. Callers that need a
        guaranteed row should call `get_or_create` instead.
        """
        r = await self.session.execute(
            select(GuildKarmaConfig).where(GuildKarmaConfig.guild_id == guild_id)
        )
        return r.scalar_one_or_none()

    async def get_or_create(self, guild_id: uuid.UUID) -> GuildKarmaConfig:
        """Return the config row, creating a default row on first access.

        Karma is **opt-in**: the default row has `enabled=False`, so nothing fires
        until an admin explicitly turns it on. The first call for a new guild inserts
        a row with all column defaults applied; subsequent calls return the same row.

        `flush()` materialises the PK in the current transaction; `refresh()` reloads
        server-side timestamps (created_at, updated_at) back into the ORM object,
        all without committing.
        """
        existing = await self.get(guild_id)
        if existing is not None:
            return existing
        # No row yet — create one with defaults (enabled=False).
        cfg = GuildKarmaConfig(guild_id=guild_id)
        self.session.add(cfg)
        await self.session.flush()  # materialises the PK
        await self.session.refresh(cfg)  # pulls back server-side defaults
        return cfg

    async def upsert(self, guild_id: uuid.UUID, data: dict) -> GuildKarmaConfig:
        """Apply a partial update to the config, creating defaults first if needed.

        `data` is a plain dict of field-name → new-value pairs, e.g.:
            {"enabled": True}

        Unknown keys in `data` are silently ignored (hasattr guard) so callers don't
        need to pre-filter dashboard payloads that may contain extra fields.
        """
        cfg = await self.get_or_create(guild_id)
        for field, value in data.items():
            # Only touch attributes that actually exist on the model; unknown keys
            # are silently ignored rather than raising AttributeError.
            if hasattr(cfg, field):
                setattr(cfg, field, value)
        await self.session.flush()  # persist changes within the transaction
        await self.session.refresh(cfg)  # reload so the caller sees the latest state
        return cfg
