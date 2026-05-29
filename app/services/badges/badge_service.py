"""Badges facade — gathers a member's stats, evaluates the catalog, persists
newly-earned badges, and serves the /badges view.

Reads stats through *repositories* (not sibling service facades): level is
derived from `user_xp.total_xp` via `level_for_xp`; `longest_streak` and
`balance` come straight off `user_wallet`. This keeps badges decoupled from
the leveling/currency services while still reacting to their data. Repos only
flush; the caller's session scope owns the commit.

`award_new` is intentionally silent (returns []) when the guild is unknown or
badges are disabled, because it runs on hot paths (/daily, level-up).
"""

import uuid
from datetime import datetime

from app.repositories.badge_config import BadgeConfigRepository
from app.repositories.guild import GuildRepository
from app.repositories.user_badge import BadgeRepository
from app.repositories.user_wallet import WalletRepository
from app.repositories.user_xp import UserXpRepository
from app.services.badges.catalog import BADGES, BadgeDef
from app.services.badges.evaluator import evaluate
from app.services.leveling.xp_calculator import level_for_xp


class BadgeService:
    def __init__(
        self,
        *,
        guild_repo: GuildRepository,
        badge_repo: BadgeRepository,
        badge_config_repo: BadgeConfigRepository,
        xp_repo: UserXpRepository,
        wallet_repo: WalletRepository,
    ):
        self.guild_repo = guild_repo
        self.badge_repo = badge_repo
        self.badge_config_repo = badge_config_repo
        self.xp_repo = xp_repo
        self.wallet_repo = wallet_repo

    async def _stats(self, guild_id: uuid.UUID, user_id: int) -> dict[str, int]:
        """Snapshot the member's badge-relevant stats from existing tables."""
        xp = await self.xp_repo.get(guild_id, user_id)
        wallet = await self.wallet_repo.get(guild_id, user_id)
        return {
            "level": level_for_xp(xp.total_xp) if xp else 0,
            "longest_streak": wallet.longest_streak if wallet else 0,
            "balance": wallet.balance if wallet else 0,
        }

    async def award_new(self, *, guild_discord_id: int, user_id: int) -> list[BadgeDef]:
        """Evaluate + persist any newly-earned badges; return them (catalog order).

        Silent no-op (returns []) when the guild isn't registered or badges are
        disabled, so callers on hot paths don't need to pre-check.
        """
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            return []
        cfg = await self.badge_config_repo.get(guild.id)
        if cfg is None or not cfg.enabled:
            return []
        stats = await self._stats(guild.id, user_id)
        earned = await self.badge_repo.earned_keys(guild.id, user_id)
        new = evaluate(stats, earned)
        for badge in new:
            await self.badge_repo.add(guild.id, user_id, badge.key)
        return new

    async def list_for(
        self, *, guild_discord_id: int, user_id: int
    ) -> tuple[list[tuple[BadgeDef, datetime]], list[BadgeDef], bool]:
        """Return (earned_with_dates, locked, enabled) for the /badges view.

        Never raises: an unknown guild reports everything locked + disabled.
        `earned_with_dates` is oldest-first; `locked` is the remaining catalog
        in catalog order. Earned rows whose key is no longer in the catalog
        (a badge removed after award) are skipped.
        """
        guild = await self.guild_repo.get_by_discord_id(guild_discord_id)
        if guild is None:
            return [], list(BADGES), False
        cfg = await self.badge_config_repo.get(guild.id)
        enabled = bool(cfg and cfg.enabled)
        rows = await self.badge_repo.list_earned(guild.id, user_id)
        earned_at_by_key = {r.badge_key: r.earned_at for r in rows}
        earned: list[tuple[BadgeDef, datetime]] = [
            (badge, earned_at_by_key[badge.key])
            for badge in BADGES
            if badge.key in earned_at_by_key
        ]
        earned.sort(key=lambda pair: pair[1])
        locked = [badge for badge in BADGES if badge.key not in earned_at_by_key]
        return earned, locked, enabled
