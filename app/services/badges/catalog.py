"""The hardcoded badge catalog — the single source of truth for what badges
exist and how they're earned.

A badge is earned the moment a member's stat reaches its threshold, and once
earned it is **permanent** (the comparison is one-directional `>=`, and we
never delete `user_badge` rows). v1 deliberately uses only stats that already
exist elsewhere — `level` (derived from `user_xp.total_xp`), `longest_streak`
and `balance` (both on `user_wallet`) — so badges add no new tracking.

`key` is the contract with the database (`user_badge.badge_key`): once shipped
it must never change. Renaming/re-emoji-ing/re-thresholding a badge is fine;
changing its `key` orphans every badge already awarded.
"""

from dataclasses import dataclass

# Stats the evaluator knows how to read. Keep in sync with BadgeService.
STAT_KEYS = {"level", "longest_streak", "balance"}


@dataclass(frozen=True)
class BadgeDef:
    key: str  # stable id stored in user_badge.badge_key — NEVER change after ship
    name: str
    emoji: str
    description: str  # human-facing unlock condition
    stat: str  # one of STAT_KEYS
    threshold: int  # earned when the member's `stat` >= threshold


# Order matters only for display (it's the order /badges and the catalog show).
BADGES: list[BadgeDef] = [
    # --- Level (from level_for_xp(total_xp)) ---
    BadgeDef("level_5", "Rookie", "🥉", "Reach level 5", "level", 5),
    BadgeDef("level_10", "Veteran", "🥈", "Reach level 10", "level", 10),
    BadgeDef("level_25", "Old Hand", "🥇", "Reach level 25", "level", 25),
    BadgeDef("level_50", "Legend", "👑", "Reach level 50", "level", 50),
    # --- Streak (longest_streak) ---
    BadgeDef("streak_7", "Diligent", "🔥", "Hold a 7-day streak", "longest_streak", 7),
    BadgeDef("streak_30", "Persistent", "⚡", "Hold a 30-day streak", "longest_streak", 30),
    BadgeDef("streak_100", "Iron-Willed", "💎", "Hold a 100-day streak", "longest_streak", 100),
    BadgeDef("streak_365", "Immortal", "🏆", "Hold a 365-day streak", "longest_streak", 365),
    # --- Wealth (balance) ---
    BadgeDef("wealth_1k", "Flush", "💰", "Stockpile 1,000 coins", "balance", 1_000),
    BadgeDef("wealth_10k", "Big Shot", "💵", "Stockpile 10,000 coins", "balance", 10_000),
    BadgeDef("wealth_100k", "Tycoon", "🤑", "Stockpile 100,000 coins", "balance", 100_000),
]

_BY_KEY = {b.key: b for b in BADGES}


def by_key(key: str) -> BadgeDef | None:
    """Look up a badge definition by its stable key, or None if unknown.

    Unknown keys can appear if a badge was removed from the catalog after rows
    were already awarded; callers should tolerate None.
    """
    return _BY_KEY.get(key)
