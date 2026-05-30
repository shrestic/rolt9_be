"""Pure pet math — time-decay, level, evolution stage, mood. No DB, no I/O.

The pet's two stats (hunger, happiness) decay with wall-clock time; rather than a
background job we *settle* the decay lazily whenever the pet is read or acted on
(`settle_decay`), which keeps the displayed value accurate with zero infra. Level
is derived from accumulated care-XP, and the evolution stage + mood emoji are
pure functions of level / stats.
"""

from datetime import datetime

# XP a single feed/play grants the pet.
XP_PER_ACTION = 5

# (min level, stage name, emoji) — the stage is the last entry whose min <= level.
STAGES: list[tuple[int, str, str]] = [
    (1, "Trứng", "🥚"),
    (5, "Non", "🐣"),
    (15, "Nhỡ", "🐤"),
    (30, "Trưởng thành", "🦅"),
]


def pet_level(xp: int) -> int:
    """Pet level from care-XP: 50 XP per level (~10 actions), minimum level 1."""
    return xp // 50 + 1


def stage_for(level: int) -> tuple[str, str]:
    """Return (stage name, emoji) for `level` — the highest stage it has reached."""
    chosen = STAGES[0]
    for entry in STAGES:
        if level >= entry[0]:
            chosen = entry
    return chosen[1], chosen[2]


def mood_for(hunger: int, happiness: int) -> str:
    """Mood emoji from the average of the two stats."""
    avg = (hunger + happiness) / 2
    if avg >= 70:
        return "😸"
    if avg >= 40:
        return "🙂"
    if avg >= 10:
        return "😟"
    return "😿"


def settle_decay(
    hunger: int,
    happiness: int,
    last_decay_at: datetime | None,
    now: datetime,
    decay_per_day: int,
) -> tuple[int, int]:
    """Return (hunger, happiness) after subtracting time-decay since last_decay_at.

    Decay is linear in elapsed time: drop = decay_per_day * elapsed_seconds/86400,
    applied to both stats and floored at 0. A None anchor (pet never decayed yet)
    or non-positive elapsed is a no-op — the stats are returned unchanged.
    Both timestamps must be UTC-aware.
    """
    if last_decay_at is None:
        return hunger, happiness
    elapsed = (now - last_decay_at).total_seconds()
    if elapsed <= 0:
        return hunger, happiness
    drop = int(decay_per_day * elapsed / 86400)
    return max(0, hunger - drop), max(0, happiness - drop)
