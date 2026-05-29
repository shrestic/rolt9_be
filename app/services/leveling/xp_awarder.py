"""Award XP for a single chat message.

This is the lowest-level write path in the leveling system. By the time we
get here, every gate above has already said "yes":

    XpListenerCog       → "this is a real message in a real guild"
    LevelingConfigCache → "this guild has leveling enabled"
    LevelingService     → "the channel/role/content filters all passed"

`XpAwarder` then owns the last two gates: **the cooldown** (one award per
member per `cooldown_seconds`) and **the concurrency lock** (one award at
a time per (guild, user) pair). After those, it picks a random amount in
`[xp_min, xp_max]`, recomputes the level, persists, and returns an
`AwardOutcome` for the caller to act on (level-up side effects).

Why concurrency matters here: a member can send three messages within
50 ms (paste a link → autocomplete fires → keyboard repeats). Without a
per-user lock, two `award()` calls could both read `last_xp_at`, both
decide they're past the cooldown, and both write — doubling the XP. The
lock makes the read-decide-write a critical section.

Concurrency choice — local `asyncio.Lock`:
    + Zero network: in-process map, microsecond scale.
    + Works only for a single process. Once we shard the bot across
      multiple processes, swap `_lock_for` for `pg_advisory_xact_lock(...)`
      so the database is the arbiter.
    + The lock map is an `OrderedDict` LRU capped at `LOCK_CACHE_SIZE`
      entries so it can never leak memory; an evicted (guild,user) just
      gets a fresh lock the next time they message.

Why LRU eviction is safe: an evicted user only loses race protection
during the window between their two adjacent messages. Cooldown is
seconds — the LRU window is "the next `LOCK_CACHE_SIZE` distinct
(guild,user) pairs that chat" which is many minutes even on busy guilds.
"""

import asyncio
import random
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guild_leveling_config import GuildLevelingConfig
from app.repositories.user_xp import UserXpRepository
from app.services.leveling.xp_calculator import level_for_xp

# Cap on the per-(guild,user) lock map. 10 000 distinct chatters fits a
# very busy server; an evicted entry just means the next race-window
# (sub-cooldown burst) for that user isn't protected. See module docstring.
LOCK_CACHE_SIZE = 10_000


@dataclass(frozen=True)
class AwardOutcome:
    """Result of a successful XP award.

    The caller (`LevelingService.process_message`) uses this to decide
    whether to run level-up side effects: if `new_level > old_level`,
    trigger role sync + notification.

    Attributes:
        amount: How much XP was added on this call. Random integer in
            `[config.xp_min, config.xp_max]`.
        old_level: The member's level *before* this award.
        new_level: The member's level *after* this award. Equal to
            `old_level` for awards that didn't cross a threshold.
        total_xp: Cumulative XP after this award. Used by callers that
            want to log or echo it back.
    """

    amount: int
    old_level: int
    new_level: int
    total_xp: int


class XpAwarder:
    """Owns the cooldown gate, per-user lock, and the XP write.

    Lives for the duration of the surrounding `LevelingService`; that
    service is built per request / per `on_message` event by DI, so each
    `XpAwarder` instance is short-lived and the `_locks` map is fresh
    each time. (If we ever pool `LevelingService` across requests, the
    LRU cap still keeps `_locks` safe.)
    """

    def __init__(self, session: AsyncSession, xp_repo: UserXpRepository):
        """Store dependencies and initialise the lock map.

        Args:
            session: The active SQLAlchemy `AsyncSession`. We don't commit
                here (UoW pattern); the caller's `get_db` / `session_scope`
                does that at the boundary.
            xp_repo: Repository over `user_xp`, sharing the same session.
        """
        self.session = session
        self.xp_repo = xp_repo
        # `OrderedDict` makes LRU eviction a one-liner: `popitem(last=False)`
        # removes the oldest entry, `move_to_end(key)` marks "just used".
        self._locks: OrderedDict[tuple[uuid.UUID, int], asyncio.Lock] = OrderedDict()

    def _lock_for(self, guild_id: uuid.UUID, user_id: int) -> asyncio.Lock:
        """Return the `asyncio.Lock` for a given (guild, user) pair.

        Creates one on first access; reuses on subsequent access. Maintains
        LRU order so the cache eviction doesn't accidentally drop active
        chatters.

        Args:
            guild_id: Internal UUID of the guild.
            user_id: Discord snowflake of the member.

        Returns:
            An `asyncio.Lock`. Callers must `async with` it; this function
            does not acquire it.
        """
        key = (guild_id, user_id)
        lock = self._locks.get(key)
        if lock is None:
            # First time we've seen this pair — mint a fresh lock and
            # insert it as the most-recently-used.
            lock = asyncio.Lock()
            self._locks[key] = lock
            # If we just blew past the cap, drop the least-recently-used
            # entry. `popitem(last=False)` pops from the front (oldest).
            if len(self._locks) > LOCK_CACHE_SIZE:
                self._locks.popitem(last=False)
        else:
            # Existing lock — mark it as just-used so it survives future
            # evictions.
            self._locks.move_to_end(key)
        return lock

    async def award(
        self,
        *,
        guild_id: uuid.UUID,
        user_id: int,
        config: GuildLevelingConfig,
    ) -> AwardOutcome | None:
        """Try to award XP for one message; return the outcome or None.

        The full sequence:
            1. Acquire the per-(guild,user) lock. Serialises bursts.
            2. Load or create the `user_xp` row.
            3. Cooldown gate: if the last award was less than
               `config.cooldown_seconds` ago, **return None** without
               touching anything.
            4. Roll a random amount in `[xp_min, xp_max]`.
            5. Recompute the level on the *new* total (so we can tell the
               caller whether to fire level-up side effects).
            6. Persist via `xp_repo.set_xp(...)` (flush only; commit happens
               at the request/session boundary).
            7. Return the `AwardOutcome`.

        The lock scope wraps everything from "read row" to "write row",
        so two concurrent calls for the same user serialise cleanly.

        Args:
            guild_id: Internal UUID of the guild.
            user_id: Discord snowflake of the member.
            config: The full `GuildLevelingConfig` row. We read xp_min,
                xp_max, and cooldown_seconds.

        Returns:
            An `AwardOutcome` on success. `None` when the cooldown gate
            rejected the message — the caller treats `None` as "skip
            level-up side effects, this message earned nothing".

        Example:
            >>> outcome = await awarder.award(
            ...     guild_id=gid, user_id=42, config=cfg
            ... )
            >>> if outcome and outcome.new_level > outcome.old_level:
            ...     # level-up! → run role sync + notification
        """
        async with self._lock_for(guild_id, user_id):
            # Load or create the row. `get_or_create` flushes for us so
            # the returned row has its PK + defaults populated.
            row = await self.xp_repo.get_or_create(guild_id, user_id)

            # Cooldown gate. Compare `last_xp_at` (UTC, may be naive if
            # SQLite stripped tz) with now. First-ever award has
            # last_xp_at = None → fall through to the award path.
            now = datetime.now(UTC)
            if row.last_xp_at is not None:
                last = row.last_xp_at
                # Normalise to UTC-aware. Some DB engines (SQLite in tests)
                # return naive datetimes even when the column is `timezone=True`;
                # tagging them with UTC keeps the subtraction safe.
                if last.tzinfo is None:
                    last = last.replace(tzinfo=UTC)
                elapsed = (now - last).total_seconds()
                if elapsed < config.cooldown_seconds:
                    # Within cooldown — silently reject. `None` lets the
                    # caller short-circuit the level-up side-effect work.
                    return None

            # Roll the award. `randint` is inclusive on both ends, matching
            # MEE6's behaviour where `xp_min == xp_max` would just mean
            # "always award that exact amount".
            amount = random.randint(config.xp_min, config.xp_max)

            # Capture the old level so we can tell the caller whether the
            # award crossed a threshold (level-up).
            old_level = level_for_xp(row.total_xp)
            new_total = row.total_xp + amount
            new_level = level_for_xp(new_total)

            # Persist. `set_xp` updates `total_xp` and `last_xp_at` in one
            # call. Flush only — the surrounding session's commit boundary
            # finalises the transaction.
            await self.xp_repo.set_xp(guild_id, user_id=user_id, total_xp=new_total, last_xp_at=now)

            return AwardOutcome(
                amount=amount,
                old_level=old_level,
                new_level=new_level,
                total_xp=new_total,
            )
