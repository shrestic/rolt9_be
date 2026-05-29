"""Data access for `guild_badge_config` — the per-guild badges on/off switch.

Same "no 404 / always-returns-defaults" pattern as CurrencyConfigRepository:
`get_or_create` hides whether the guild has a row yet, defaulting to disabled.
There is at most one row per guild (guild_id is the PK), so the interface is
just: get, get_or_create, upsert — no pagination needed. Flush only; commit
at the boundary (Unit-of-Work).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guild_badge_config import GuildBadgeConfig


class BadgeConfigRepository:
    """Repository for reading and mutating a guild's badge feature configuration.

    Badges are **opt-in**: a freshly-created row has `enabled=False`, so no
    badge logic fires until an admin explicitly enables it from the dashboard.
    """

    def __init__(self, session: AsyncSession):
        # Hold a reference to the async session injected by FastAPI's `get_db`
        # dependency.  All methods share this session so they participate in the
        # same Unit-of-Work transaction.
        self.session = session

    async def get(self, guild_id: uuid.UUID) -> GuildBadgeConfig | None:
        """Return the config row for `guild_id`, or None if it doesn't exist yet.

        Used internally by `get_or_create` and `upsert`. Callers that need a
        guaranteed row should call `get_or_create` instead.
        """
        r = await self.session.execute(
            select(GuildBadgeConfig).where(GuildBadgeConfig.guild_id == guild_id)
        )
        return r.scalar_one_or_none()

    async def get_or_create(self, guild_id: uuid.UUID) -> GuildBadgeConfig:
        """Return the config row, creating a default row on first access.

        This is the heart of the "no 404" pattern: callers never branch on
        whether the guild has been configured — they call this and always get
        back a usable object.

        The first time this is called for a guild, a new `GuildBadgeConfig`
        is inserted with all SQLAlchemy column `default=` values applied:
            enabled=False.

        `flush()` sends the INSERT within the current transaction so the row
        gets a real PK, and `refresh()` pulls back server-side defaults
        (created_at, updated_at) — all without committing.
        """
        existing = await self.get(guild_id)
        if existing is not None:
            return existing

        # No row yet — create one with defaults (enabled=False).
        # We don't pass field values; column `default=` declarations in
        # GuildBadgeConfig keep defaults in one place.
        cfg = GuildBadgeConfig(guild_id=guild_id)
        self.session.add(cfg)
        await self.session.flush()  # materialises the row within the transaction
        await self.session.refresh(cfg)  # pulls back server-side defaults
        return cfg

    async def upsert(self, guild_id: uuid.UUID, data: dict) -> GuildBadgeConfig:
        """Apply a partial update to the config, creating defaults first if needed.

        `data` is a plain dict of field-name → new-value pairs, e.g.:
            {"enabled": True}

        Unknown keys are silently ignored (defensive `hasattr` guard) — the
        dashboard might send extra/future fields that don't map to columns, and
        silently skipping them is safer than raising AttributeError.
        """
        cfg = await self.get_or_create(guild_id)

        for field, value in data.items():
            # Only touch attributes that actually exist on the model.
            if hasattr(cfg, field):
                setattr(cfg, field, value)

        await self.session.flush()  # persist the changes
        await self.session.refresh(cfg)  # reload so the caller sees the latest state
        return cfg
