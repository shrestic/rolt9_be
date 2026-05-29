"""Pure badge evaluation — given a stat snapshot and the badges already earned,
return the badge definitions newly unlocked.

No DB, no I/O: this is the testable heart of the awarding logic. The service
layer gathers the stats and persists the result; this function only decides
*which* badges a snapshot qualifies for that aren't already held.
"""

from app.services.badges.catalog import BADGES, BadgeDef


def evaluate(stats: dict[str, int], earned: set[str]) -> list[BadgeDef]:
    """Return catalog badges whose threshold is met but which aren't in `earned`.

    Args:
        stats: Current values keyed by stat name, e.g.
            {"level": 12, "longest_streak": 8, "balance": 1500}. A missing key
            is treated as 0 (so a partially-populated snapshot is safe).
        earned: Set of badge keys the member already holds.

    Returns:
        Newly-earned BadgeDefs, in catalog order. Empty if nothing new qualifies.
    """
    return [
        badge
        for badge in BADGES
        if badge.key not in earned and stats.get(badge.stat, 0) >= badge.threshold
    ]
