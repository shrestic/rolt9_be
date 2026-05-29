"""Data access for `guild_currency_config` — per-guild server-currency settings.

Design: "no 404 / always-returns-defaults" pattern
---------------------------------------------------
Most callers don't want to think about whether a guild has been configured yet.
`get_or_create` hides that concern: call it and you always get back a usable
config row — either an existing one or a freshly-seeded one with sane defaults
(currency off, name "coins", earn 1–3 per message, 100-coin daily, pay allowed).

Currency is **opt-in**: the default row has `enabled=False`, so nothing fires
until an admin explicitly turns it on. That keeps new guilds safe from surprise
coin spam.

Commit boundary
---------------
Like every repository in this codebase, we only `flush()` — we never `commit()`.
The commit is owned by the surrounding `get_db` dependency / `session_scope`
context (Unit-of-Work pattern). This lets multiple repository calls participate
in the same transaction without stepping on each other.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guild_currency_config import GuildCurrencyConfig


class CurrencyConfigRepository:
    """Repository for reading and mutating a guild's currency configuration.

    There is at most one `GuildCurrencyConfig` row per guild (guild_id is the
    primary key), so the interface is simple: get, get_or_create, upsert. No
    pagination or bulk operations are needed here.
    """

    def __init__(self, session: AsyncSession):
        # We hold a reference to the async session injected by FastAPI's
        # `get_db` dependency.  All methods share this session so they
        # participate in the same Unit-of-Work transaction.
        self.session = session

    async def get(self, guild_id: uuid.UUID) -> GuildCurrencyConfig | None:
        """Return the config row for `guild_id`, or None if it doesn't exist yet.

        Used internally by `get_or_create` and `upsert`.  Callers that need a
        guaranteed row should call `get_or_create` instead.
        """
        r = await self.session.execute(
            select(GuildCurrencyConfig).where(GuildCurrencyConfig.guild_id == guild_id)
        )
        return r.scalar_one_or_none()

    async def get_or_create(self, guild_id: uuid.UUID) -> GuildCurrencyConfig:
        """Return the config row, creating a default row on first access.

        This is the heart of the "no 404" pattern: callers never have to branch
        on whether the guild has been configured — they just call this and get
        back a ready-to-use object.

        The first time this is called for a guild, a new `GuildCurrencyConfig`
        is inserted with all SQLAlchemy column `default=` values applied:
            enabled=False, currency_name="coins", earn_min=1, earn_max=3,
            daily_amount=100, allow_pay=True.

        `flush()` sends the INSERT to the DB within the current transaction so
        the row gets a real PK, and `refresh()` reloads server-side defaults
        (created_at, updated_at) back into the ORM object — all without
        committing.
        """
        existing = await self.get(guild_id)
        if existing is not None:
            return existing

        # No row yet — create one with defaults.  We don't pass any field
        # values; we rely entirely on the column `default=` declarations in
        # GuildCurrencyConfig so that defaults stay in one place.
        cfg = GuildCurrencyConfig(guild_id=guild_id)
        self.session.add(cfg)
        await self.session.flush()  # materialises the PK
        await self.session.refresh(cfg)  # pulls back server-side defaults
        return cfg

    async def upsert(self, guild_id: uuid.UUID, data: dict) -> GuildCurrencyConfig:
        """Apply a partial update to the config, creating defaults first if needed.

        `data` is a plain dict of field-name → new-value pairs, e.g.:
            {"enabled": True, "currency_name": "xu", "daily_amount": 150}

        Why `hasattr` guard: the dashboard might send extra keys (version fields,
        computed properties, unknown future additions) that don't map to model
        columns. Silently skipping unknown keys is more defensive than raising
        — the valid fields still get applied, and the caller doesn't need to
        pre-filter.

        Only `flush()` here, same as `get_or_create`. The transaction is
        committed by the caller's session scope.
        """
        cfg = await self.get_or_create(guild_id)

        for field, value in data.items():
            # Defensive: only touch attributes that actually exist on the model.
            # Unknown keys are silently ignored rather than raising AttributeError.
            if hasattr(cfg, field):
                setattr(cfg, field, value)

        await self.session.flush()  # persist the changes to the DB
        await self.session.refresh(cfg)  # reload so caller sees latest state
        return cfg
