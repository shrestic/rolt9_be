"""Quests facade — records progress on events, lists a member's quests, and
claims completed ones for coins.

Reads quest definitions + progress via repositories and grants the reward
through `WalletRepository.add_balance` directly (coins are coins — we don't go
through CurrencyService, keeping quests decoupled from it). Repos flush only;
the caller's session scope owns the commit.

`record_event` runs on hot paths (passive earn, /daily), so it's silent: an
unknown guild or no matching quests is a no-op.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from app.models.guild_quest import GuildQuest
from app.repositories.guild import GuildRepository
from app.repositories.quest import QuestRepository
from app.repositories.quest_progress import QuestProgressRepository
from app.repositories.user_wallet import WalletRepository
from app.services.quests.quest_period import period_key


@dataclass(frozen=True)
class QuestView:
    """A quest plus the viewing member's standing on it this period."""

    quest: GuildQuest
    progress: int
    target: int
    completed: bool
    claimed: bool


@dataclass(frozen=True)
class ClaimResult:
    """Outcome of a claim-all."""

    claimed_count: int
    total_coins: int
    names: list[str]


def _as_utc(dt: datetime) -> datetime:
    """Ensure `dt` is UTC-aware; naive datetimes are treated as UTC."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class QuestService:
    def __init__(
        self,
        *,
        guild_repo: GuildRepository,
        quest_repo: QuestRepository,
        progress_repo: QuestProgressRepository,
        wallet_repo: WalletRepository,
    ):
        # All four repos share the same session, so they operate inside the
        # same Unit-of-Work transaction managed by the caller.
        self.guild_repo = guild_repo
        self.quest_repo = quest_repo
        self.progress_repo = progress_repo
        self.wallet_repo = wallet_repo

    async def record_event(
        self,
        *,
        guild_discord_id: int,
        user_id: int,
        objective_type: str,
        amount: int,
        now: datetime | None = None,
    ) -> None:
        """Add `amount` to every enabled quest of this objective for the member.

        Called on hot paths (passive message earn, /daily command) so it must
        be silent: an unknown guild, non-positive amount, or no matching quests
        all produce a clean no-op. Never raises.
        """
        # Guard: nonsensical amounts do nothing (negative delta or zero).
        if amount <= 0:
            return

        # Resolve the internal guild UUID from the Discord snowflake.
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            # Unknown guild — silent no-op rather than raising, because the
            # caller may fire events before the guild has been registered.
            return

        now = _as_utc(now or datetime.now(UTC))

        # Only fetch quests that match this event type — avoids touching
        # unrelated quest counters and keeps the loop tight.
        quests = await self.quest_repo.list_enabled(guild.id, objective_type=objective_type)
        for quest in quests:
            # period_key() maps the timestamp to the current daily/weekly
            # bucket; `increment` creates the row on first call.
            await self.progress_repo.increment(
                quest.id, guild.id, user_id, period_key(quest.period, now), amount
            )

    async def list_quests(
        self, *, guild_discord_id: int, user_id: int, now: datetime | None = None
    ) -> list[QuestView]:
        """All enabled quests + the member's progress/claimed state this period.

        Returns an empty list for an unknown guild — never raises. The returned
        QuestView objects are frozen dataclasses, safe to cache or pass to the
        presentation layer without defensive copying.
        """
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            return []

        now = _as_utc(now or datetime.now(UTC))
        quests = await self.quest_repo.list_enabled(guild.id)

        # Build the set of active period keys (daily + weekly) so we can
        # fetch all progress rows in one query instead of N queries.
        keys = {period_key("daily", now), period_key("weekly", now)}
        by_quest = await self.progress_repo.list_for(guild.id, user_id, keys)

        views: list[QuestView] = []
        for quest in quests:
            row = by_quest.get(quest.id)
            # A missing row means no progress has been recorded this period.
            progress = row.progress if row else 0
            claimed = row.claimed if row else False
            views.append(
                QuestView(
                    quest=quest,
                    progress=progress,
                    target=quest.target,
                    # completed = hit the target; claimed = coins already taken.
                    completed=progress >= quest.target,
                    claimed=claimed,
                )
            )
        return views

    async def claim(
        self, *, guild_discord_id: int, user_id: int, now: datetime | None = None
    ) -> ClaimResult:
        """Claim every completed-unclaimed quest; grant coins; return a summary.

        Each quest is claimed via `try_claim`, which is an atomic guarded
        UPDATE (`progress >= target AND claimed = false` in the WHERE), so a
        double-fire can never pay twice — the second UPDATE matches 0 rows and
        returns False. Never raises; unknown guild → empty ClaimResult.
        """
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            return ClaimResult(claimed_count=0, total_coins=0, names=[])

        now = _as_utc(now or datetime.now(UTC))
        quests = await self.quest_repo.list_enabled(guild.id)

        total = 0
        names: list[str] = []
        for quest in quests:
            # try_claim is the single-flight atomic guard — returns True only
            # if this specific call was the one that flipped claimed=True.
            claimed = await self.progress_repo.try_claim(
                quest.id, user_id, period_key(quest.period, now), target=quest.target
            )
            if claimed:
                # Grant the reward directly through the wallet repo; no need
                # to go through CurrencyService (which adds overhead and
                # circular-dependency risk).
                await self.wallet_repo.add_balance(guild.id, user_id, quest.reward_coins)
                total += quest.reward_coins
                names.append(quest.name)

        return ClaimResult(claimed_count=len(names), total_coins=total, names=names)
