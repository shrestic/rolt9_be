"""Pure streak math for the daily-claim chain — no DB, no I/O.

Mirrors `app/services/leveling/xp_calculator.py`: a small set of deterministic
functions the currency service composes. Keeping it pure means the streak
rules (window, bonus curve, milestones) are unit-tested in isolation and the
service stays a thin orchestrator.

The streak is driven entirely by `/daily`. Because the daily cooldown is 24h,
a member can claim at most once per day; to *keep* the chain alive they must
claim again before a full day is skipped — i.e. within 48h of the previous
claim. Past 48h the chain is considered broken and restarts at 1.
"""

from datetime import datetime, timedelta

# Claim again within this window of the previous claim to keep the chain.
# 48h = "you may miss being punctual, but not a whole day".
STREAK_WINDOW = timedelta(hours=48)

# Lump-sum coin rewards granted the day a member's streak first reaches the key.
# Hardcoded in v1 (not FE-configurable); tuned so day-7 ≈ 2× a default daily.
MILESTONES: dict[int, int] = {7: 200, 30: 1000, 100: 5000, 365: 20000}


def next_streak(last_claim_at: datetime | None, now: datetime, current: int) -> int:
    """Return the streak count after a successful claim at `now`.

    - Never claimed (`last_claim_at is None`) → 1 (chain starts).
    - Claimed within `STREAK_WINDOW` (≤48h ago) → `current + 1` (chain continues).
    - Otherwise → 1 (a full day was skipped, chain restarts).

    Args:
        last_claim_at: Timestamp of the member's previous `/daily` claim, or
            None if they have never claimed.
        now: The timestamp of the current claim (typically `datetime.now(UTC)`).
        current: The member's streak count before this claim. Ignored if the
            chain breaks (reset to 1) or if this is the first ever claim.

    Returns:
        The new streak integer, always >= 1.

    Example:
        >>> from datetime import UTC, datetime, timedelta
        >>> now = datetime(2026, 5, 29, 12, 0, tzinfo=UTC)
        >>> next_streak(None, now, 0)
        1
        >>> next_streak(now - timedelta(hours=30), now, 5)
        6
        >>> next_streak(now - timedelta(hours=49), now, 5)
        1
    """
    if last_claim_at is None:
        return 1
    if now - last_claim_at <= STREAK_WINDOW:
        return current + 1
    return 1


def streak_bonus(streak: int, *, per_day: int, cap: int) -> int:
    """Escalating per-day bonus, clamped so long chains can't inflate forever.

    = min(streak * per_day, cap). With per_day=10, cap=500 the bonus grows
    +10/day and tops out at a 50-day chain.

    Args:
        streak: Current streak count (after increment, not before).
        per_day: Extra coins awarded per day of streak. Passed as a keyword
            arg to make call sites self-documenting.
        cap: Maximum bonus regardless of streak length. Also keyword-only.

    Returns:
        Bonus coins to add to the base daily reward, in [0, cap].

    Example:
        >>> streak_bonus(3, per_day=10, cap=500)
        30
        >>> streak_bonus(1000, per_day=10, cap=500)
        500
    """
    return min(streak * per_day, cap)


def milestone_reward(streak: int) -> int:
    """Lump-sum reward if `streak` lands exactly on a milestone, else 0.

    Streaks only ever step +1 or reset to 1, so every milestone value is hit
    exactly. Re-earning after a reset is intentional (and not farmable — it
    costs another full run of consecutive days).

    Args:
        streak: The member's current streak count (post-increment).

    Returns:
        The lump-sum coin bonus for hitting that milestone, or 0 if `streak`
        is not in MILESTONES.

    Example:
        >>> milestone_reward(7)
        200
        >>> milestone_reward(8)
        0
    """
    return MILESTONES.get(streak, 0)


def days_to_next_milestone(streak: int) -> int | None:
    """Days remaining until the next milestone, or None past the final one.

    Useful for progress-bar UX ("X days until your next big reward!").

    Args:
        streak: Current streak count.

    Returns:
        Positive integer representing how many more consecutive days are needed
        to hit the next milestone, or None if `streak` is already at or past
        the highest milestone (no further milestones exist).

    Example:
        >>> days_to_next_milestone(3)
        4
        >>> days_to_next_milestone(7)
        23
        >>> days_to_next_milestone(365)  # highest milestone
        None
    """
    # Collect all milestone days that are strictly ahead of the current streak,
    # in ascending order. The first element is the nearest upcoming milestone.
    upcoming = [day for day in sorted(MILESTONES) if day > streak]
    return upcoming[0] - streak if upcoming else None
