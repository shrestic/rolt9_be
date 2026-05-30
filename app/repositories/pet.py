"""Data access for `guild_pet` — the per-guild shared pet (state + config).

"No 404 / get_or_create" pattern like the currency config: callers always get a
usable row (off by default). `save_state` persists settled stats + XP after an
action; `upsert_config` applies admin changes. Flush only; commit at the boundary.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guild_pet import GuildPet


class PetRepository:
    def __init__(self, session: AsyncSession):
        # Holds the async session injected by FastAPI's `get_db` dependency.
        # All methods share this session so they participate in the same
        # Unit-of-Work transaction — flush only, never commit.
        self.session = session

    async def get(self, guild_id: uuid.UUID) -> GuildPet | None:
        """Return the pet row for `guild_id`, or None if it doesn't exist yet.

        Used internally by `get_or_create` and `upsert_config`. Callers that
        need a guaranteed row should call `get_or_create` instead.
        """
        r = await self.session.execute(select(GuildPet).where(GuildPet.guild_id == guild_id))
        return r.scalar_one_or_none()

    async def get_or_create(self, guild_id: uuid.UUID) -> GuildPet:
        """Return the pet row, creating a default row on first access.

        This is the "no 404" pattern: callers never have to branch on whether
        the guild has a pet yet — they just call this and get back a ready-to-use
        object. The newly-created row has all SQLAlchemy column `default=` values:
            enabled=False, name="Pet", hunger=100, happiness=100, xp=0,
            feed_cost=10, feed_amount=30, play_amount=30, decay_per_day=20.

        `flush()` materialises the row's PK so callers can use it within the
        same transaction; `refresh()` pulls back server-side defaults
        (created_at, updated_at) without committing.
        """
        existing = await self.get(guild_id)
        if existing is not None:
            return existing

        # No row yet — rely on column `default=` declarations in GuildPet so
        # that defaults live in exactly one place (the model).
        pet = GuildPet(guild_id=guild_id)
        self.session.add(pet)
        await self.session.flush()  # materialises the PK within the transaction
        await self.session.refresh(pet)  # pulls back server-side defaults
        return pet

    async def save_state(
        self,
        pet: GuildPet,
        *,
        hunger: int,
        happiness: int,
        xp: int,
        last_decay_at: datetime,
    ) -> GuildPet:
        """Persist post-action live state (settled stats + XP + decay anchor).

        Called after every feed/play action once pet_logic has calculated the
        new stats. Keyword-only args prevent accidental positional swaps between
        hunger and happiness. Flush only — commit owned by the session boundary.
        """
        pet.hunger = hunger
        pet.happiness = happiness
        pet.xp = xp
        # Anchor for the next lazy decay calculation (elapsed = now - last_decay_at).
        pet.last_decay_at = last_decay_at
        await self.session.flush()
        await self.session.refresh(pet)
        return pet

    async def upsert_config(self, guild_id: uuid.UUID, data: dict) -> GuildPet:
        """Apply a partial config update (enabled/name/costs/decay), creating first.

        `data` is a plain dict of field-name → new-value pairs, e.g.:
            {"enabled": True, "name": "Rex", "feed_cost": 25}

        Unknown keys are silently ignored (same defensive pattern as
        CurrencyConfigRepository.upsert), so the dashboard can send extra fields
        without breaking this method.
        """
        pet = await self.get_or_create(guild_id)

        for field, value in data.items():
            # Only touch attributes that actually exist on the model; skip
            # unknown keys defensively rather than raising AttributeError.
            if hasattr(pet, field):
                setattr(pet, field, value)

        await self.session.flush()
        await self.session.refresh(pet)
        return pet
