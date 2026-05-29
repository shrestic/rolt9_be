"""XP ↔ level conversion math.

This module is the single source of truth for "given X total XP, what level
is the user?" and "how much XP does it take to clear level L?". Every other
leveling component (awarder, leaderboard, endpoints, rank card) reads from
here instead of recomputing.

Why MEE6's formula? Most Discord users have seen MEE6 or Tatsu, and we want
the leveling curve to feel identical so migrating servers don't surprise
their members. The curve is:

    xp_to_next(L) = 5*L^2 + 50*L + 100

So levelling from L → L+1 needs 100 XP at L=0, 155 XP at L=1, 220 XP at L=2,
and so on (quadratic growth).

Implementation choices:

- We precompute a list `_thresholds` of cumulative XP at the start of each
  level once at import time. `_thresholds[5]` is "total XP needed to be
  level 5". This makes both `total_xp_for_level` and `level_for_xp` cheap
  (O(1) and O(log MAX_LEVEL) respectively) and avoids any per-call alloc.
- No locks: the table is built before any await point can be reached, so
  it's effectively immutable by the time async tasks see it.
- The functions are pure (no I/O, no DB, no Discord) so they're safe to
  import everywhere without circular dependency risk.

If you ever need to support levels past MAX_LEVEL, raise the constant
rather than skipping the bound check — silent overflow is worse than a
loud error.
"""

# Hard cap on supported levels. 500 is far past anything achievable in a
# real server (level 500 = ~104M XP, ≈30+ years of constant chatting under
# MEE6's curve), but the cap exists so `level_for_xp` has a well-defined
# upper bound for its binary search.
MAX_LEVEL = 500

# Cumulative XP threshold at the start of each level. Built once at module
# import time:
#   _thresholds[0] = 0      (everyone starts here)
#   _thresholds[1] = 100    (100 XP to reach level 1)
#   _thresholds[2] = 255    (100 + 155 to reach level 2)
#   _thresholds[L] = sum(xp_to_next(0..L-1))
_thresholds: list[int] = [0]
for _l in range(MAX_LEVEL):
    _thresholds.append(_thresholds[-1] + 5 * _l * _l + 50 * _l + 100)


def xp_to_next(level: int) -> int:
    """Return the XP needed to advance from `level` to `level + 1`.

    Pure formula — does not touch the threshold table. Inputs are validated
    so a silently-negative `level` can't produce garbage (the bare formula
    would return -125 for level=-5, which would corrupt downstream math).

    Args:
        level: The current level. Must be in [0, MAX_LEVEL].

    Returns:
        XP cost of the next level (always positive). For example:
            xp_to_next(0) == 100
            xp_to_next(1) == 155
            xp_to_next(10) == 1100

    Raises:
        ValueError: If `level` is negative or exceeds MAX_LEVEL.

    Example:
        >>> xp_to_next(0)
        100
        >>> xp_to_next(5)
        475
    """
    if level < 0:
        raise ValueError("level must be non-negative")
    if level > MAX_LEVEL:
        raise ValueError(f"level exceeds MAX_LEVEL ({MAX_LEVEL})")
    return 5 * level * level + 50 * level + 100


def total_xp_for_level(level: int) -> int:
    """Return the cumulative XP required to *be* at `level`.

    This is the floor of the level — a user with exactly this much XP is
    on the boundary of `level`. Used for "XP into current level" math:

        xp_into_level = total_xp - total_xp_for_level(level)

    Args:
        level: A non-negative integer in [0, MAX_LEVEL]. 0 means "no XP at all".

    Returns:
        Sum of `xp_to_next(0..level-1)`. O(1) lookup against the precomputed
        threshold table.

    Raises:
        ValueError: If `level` is negative or exceeds MAX_LEVEL. We raise
            instead of clamping so misuse surfaces loudly during development.

    Example:
        >>> total_xp_for_level(0)
        0
        >>> total_xp_for_level(1)
        100
        >>> total_xp_for_level(2)
        255
    """
    if level < 0:
        raise ValueError("level must be non-negative")
    if level > MAX_LEVEL:
        raise ValueError(f"level exceeds MAX_LEVEL ({MAX_LEVEL})")
    return _thresholds[level]


def level_for_xp(total_xp: int) -> int:
    """Return the highest level the user has *reached* given `total_xp`.

    "Reached" means the threshold of that level has been met. For example,
    255 total XP gets you to level 2 even by one XP; 254 keeps you at level 1.

    The lookup uses binary search over the cumulative threshold table, so
    it's O(log MAX_LEVEL) ≈ 9 comparisons in the worst case — cheap enough
    to call on every chat message.

    Args:
        total_xp: Cumulative XP of the user. Negative values are silently
            treated as 0 because some callers (e.g. fresh user with no row)
            pass defaults that could theoretically underflow; the safe
            answer is "level 0".

    Returns:
        The matching level, clamped at MAX_LEVEL. Always non-negative.

    Example:
        >>> level_for_xp(0)
        0
        >>> level_for_xp(99)
        0
        >>> level_for_xp(100)
        1
        >>> level_for_xp(255)
        2
        >>> level_for_xp(10_000_000)  # Way past anything realistic
        211
    """
    if total_xp < 0:
        return 0

    # Standard binary search for the largest index `lo` such that
    # `_thresholds[lo] <= total_xp`. We work in the closed range
    # [0, MAX_LEVEL] because both endpoints are valid answers.
    lo, hi = 0, MAX_LEVEL
    while lo < hi:
        # Bias mid toward `hi` (rounding up) so we make progress when
        # `lo == hi - 1` — without the +1 we'd loop forever in that case.
        mid = (lo + hi + 1) // 2
        if _thresholds[mid] <= total_xp:
            # `mid` is still reachable; try to push the floor higher.
            lo = mid
        else:
            # `mid` overshoots; cap the ceiling just below it.
            hi = mid - 1
    return lo


def apply_decay(total_xp: int, *, level_floor: int, percent: int, periods: int) -> int:
    """Return XP after `periods` rounds of `percent`% decay, floored at a level.

    Decay compounds on the remainder: each period removes `percent`% of what
    is left. The result is clamped so it never drops below `level_floor` — the
    cumulative XP threshold of the member's current level — which is what keeps
    a member's level (and therefore their reward roles) from ever decreasing.

    Args:
        total_xp: Current cumulative XP.
        level_floor: `total_xp_for_level(level_for_xp(total_xp))` — the floor of
            the member's current level. Decay never goes below this.
        percent: Percent removed per period, 1-100 (per-guild config).
        periods: How many full inactivity periods have elapsed. <= 0 is a no-op.

    Returns:
        The new cumulative XP, an int >= level_floor.

    Example:
        >>> apply_decay(1000, level_floor=770, percent=10, periods=2)
        810
        >>> apply_decay(1000, level_floor=770, percent=10, periods=4)
        770
    """
    if periods <= 0:
        return total_xp
    decayed = round(total_xp * (1 - percent / 100) ** periods)
    return max(level_floor, decayed)
