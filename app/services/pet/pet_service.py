"""Server Pet facade — read status, feed (costs coins), play (free + cooldown).

Settles time-decay (pet_logic.settle_decay) on every read and action so stats are
always current without a background job. Feeding spends coins via
`WalletRepository.add_balance(-cost)` directly (no CurrencyService coupling);
playing is gated by an atomic per-user cooldown. Reads never write (status is
computed); actions persist the settled+mutated state. Repos flush; the caller's
session scope commits.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.repositories.guild import GuildRepository
from app.repositories.pet import PetRepository
from app.repositories.pet_cooldown import PetCooldownRepository
from app.repositories.user_wallet import WalletRepository
from app.services.pet.pet_logic import (
    XP_PER_ACTION,
    mood_for,
    pet_level,
    settle_decay,
    stage_for,
)

# How long a member must wait between /pet play uses.
PLAY_COOLDOWN = timedelta(hours=1)
# Both hunger and happiness are capped at 100.
MAX_STAT = 100


@dataclass(frozen=True)
class PetStatus:
    """Snapshot of the pet's state after lazy decay settlement — safe to serialise."""

    name: str
    hunger: int
    happiness: int
    xp: int
    level: int
    stage_name: str
    stage_emoji: str
    mood_emoji: str
    # Mirrors pet.enabled so callers never need to re-query the model.
    enabled: bool


@dataclass(frozen=True)
class PetActionResult:
    """Return value from feed() / play() — status + change signals for the caller."""

    status: PetStatus
    leveled_up: bool  # True when the action pushed the pet to a higher level.
    evolved: bool  # True when the new level crossed an evolution stage boundary.
    balance: int  # Remaining coin balance for the acting user (-1 if irrelevant).


def _as_utc(dt: datetime) -> datetime:
    """Attach UTC if the datetime has no tzinfo (SQLite stores naive datetimes)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _status(pet, hunger: int, happiness: int) -> PetStatus:
    """Build a PetStatus from settled stats — always derives level/stage/mood freshly."""
    level = pet_level(pet.xp)
    name, emoji = stage_for(level)
    return PetStatus(
        name=pet.name,
        hunger=hunger,
        happiness=happiness,
        xp=pet.xp,
        level=level,
        stage_name=name,
        stage_emoji=emoji,
        mood_emoji=mood_for(hunger, happiness),
        enabled=pet.enabled,
    )


class PetService:
    """Guild-scoped facade for the server pet feature.

    Injected with four repositories so it never imports other service-layer
    classes — keeping the dependency graph flat and testable with just a DB
    session. All mutating methods call `save_state` / repo flushes and leave
    the final `commit()` to the FastAPI session scope (Unit-of-Work).
    """

    def __init__(
        self,
        *,
        guild_repo: GuildRepository,
        pet_repo: PetRepository,
        cooldown_repo: PetCooldownRepository,
        wallet_repo: WalletRepository,
    ):
        self.guild_repo = guild_repo
        self.pet_repo = pet_repo
        self.cooldown_repo = cooldown_repo
        self.wallet_repo = wallet_repo

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_status(self, *, guild_discord_id: int) -> PetStatus | None:
        """Return settled pet status for display. None if the guild is unknown.

        This is a read-only operation — decay is *computed* but not persisted.
        The returned PetStatus reflects what the stats would be right now if we
        applied the elapsed time-decay, without touching the DB.
        """
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            return None
        pet = await self.pet_repo.get(guild.id)
        if pet is None:
            # Guild exists but pet feature was never enabled — return a sensible
            # disabled sentinel so the caller can show "pet not configured" UI.
            level = pet_level(0)
            name, emoji = stage_for(level)
            return PetStatus(
                name="Pet",
                hunger=100,
                happiness=100,
                xp=0,
                level=level,
                stage_name=name,
                stage_emoji=emoji,
                mood_emoji=mood_for(100, 100),
                enabled=False,
            )
        now = _as_utc(datetime.now(UTC))
        hunger, happiness = self._settle(pet, now)
        return _status(pet, hunger, happiness)

    async def feed(
        self, *, guild_discord_id: int, user_id: int, now: datetime | None = None
    ) -> PetActionResult:
        """Feed the pet: spend `feed_cost` coins, restore `feed_amount` hunger, earn XP.

        Raises ValueError if:
        - The guild is unknown or the pet is disabled.
        - The user has insufficient coin balance.

        Decay is settled first so hunger cannot be boosted above what it would
        naturally be; the post-decay hunger is used as the baseline.
        """
        guild = await self._enabled_guild(guild_discord_id)
        now = _as_utc(now or datetime.now(UTC))
        pet = await self.pet_repo.get_or_create(guild.id)
        old_level = pet_level(pet.xp)

        # Settle decay before the action so the displayed stats reflect elapsed time.
        hunger, happiness = self._settle(pet, now)

        # Deduct the coin cost atomically; False means the user was too poor.
        ok = await self.wallet_repo.add_balance(guild.id, user_id, -pet.feed_cost)
        if not ok:
            balance = await self._balance(guild.id, user_id)
            raise ValueError(f"Không đủ coin — cần {pet.feed_cost:,}, bạn có {balance:,}.")

        # Apply the feed: cap at MAX_STAT so hunger never exceeds 100.
        hunger = min(MAX_STAT, hunger + pet.feed_amount)
        new_xp = pet.xp + XP_PER_ACTION

        # Persist the new settled + mutated state; flush inside save_state.
        pet = await self.pet_repo.save_state(
            pet, hunger=hunger, happiness=happiness, xp=new_xp, last_decay_at=now
        )

        balance = await self._balance(guild.id, user_id)
        return self._result(pet, hunger, happiness, old_level, balance)

    async def play(
        self, *, guild_discord_id: int, user_id: int, now: datetime | None = None
    ) -> PetActionResult:
        """Play with the pet: restore `play_amount` happiness, earn XP (free, has cooldown).

        Raises ValueError if:
        - The guild is unknown or the pet is disabled.
        - The user last played within PLAY_COOLDOWN (1 hour).

        The cooldown check is atomic (single guarded UPDATE via try_play) so
        two simultaneous /pet play commands can't both succeed.
        """
        guild = await self._enabled_guild(guild_discord_id)
        now = _as_utc(now or datetime.now(UTC))

        # Atomic cooldown check-and-stamp: returns False if still on cooldown.
        allowed = await self.cooldown_repo.try_play(
            guild.id, user_id, now=now, cutoff=now - PLAY_COOLDOWN
        )
        if not allowed:
            raise ValueError("Bạn vừa chơi với pet rồi — đợi chút nhé.")

        pet = await self.pet_repo.get_or_create(guild.id)
        old_level = pet_level(pet.xp)

        # Settle decay before the action (same as feed).
        hunger, happiness = self._settle(pet, now)
        happiness = min(MAX_STAT, happiness + pet.play_amount)
        new_xp = pet.xp + XP_PER_ACTION

        pet = await self.pet_repo.save_state(
            pet, hunger=hunger, happiness=happiness, xp=new_xp, last_decay_at=now
        )
        # Playing costs nothing, so balance is not meaningful here (sentinel -1).
        return self._result(pet, hunger, happiness, old_level, balance=-1)

    # ------------------------------------------------------------------
    # Admin helpers (used by /pet config routes)
    # ------------------------------------------------------------------

    async def get_config(self, *, guild_id: uuid.UUID):
        """Return the raw GuildPet row (for admin config display)."""
        return await self.pet_repo.get_or_create(guild_id)

    async def update_config(self, *, guild_id: uuid.UUID, data: dict):
        """Apply a partial config update dict to the guild pet row."""
        return await self.pet_repo.upsert_config(guild_id, data)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _enabled_guild(self, guild_discord_id: int):
        """Resolve guild and assert the pet feature is enabled; raise ValueError otherwise."""
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            raise ValueError("Server chưa đăng ký với bot.")
        pet = await self.pet_repo.get(guild.id)
        if pet is None or not pet.enabled:
            raise ValueError("Pet chưa được bật trên server này.")
        return guild

    def _settle(self, pet, now: datetime) -> tuple[int, int]:
        """Apply time-decay to the pet's current stats and return (hunger, happiness).

        Delegates to pet_logic.settle_decay; ensures last_decay_at is tz-aware
        even when fetched from SQLite (which drops tzinfo on storage).
        """
        return settle_decay(
            pet.hunger,
            pet.happiness,
            _as_utc(pet.last_decay_at) if pet.last_decay_at else None,
            now,
            pet.decay_per_day,
        )

    async def _balance(self, guild_id: uuid.UUID, user_id: int) -> int:
        """Fetch the user's current coin balance; 0 if no wallet exists yet."""
        wallet = await self.wallet_repo.get(guild_id, user_id)
        return wallet.balance if wallet else 0

    def _result(
        self, pet, hunger: int, happiness: int, old_level: int, balance: int
    ) -> PetActionResult:
        """Build the action result, computing level-up and evolution signals."""
        new_level = pet_level(pet.xp)
        return PetActionResult(
            status=_status(pet, hunger, happiness),
            leveled_up=new_level > old_level,
            # Evolved if the new level crossed into a different named stage.
            evolved=stage_for(new_level) != stage_for(old_level),
            balance=balance,
        )
