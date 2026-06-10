"""Pure game math for the betting mini-games — no DB, no I/O.

Each function takes an injected `random.Random` (so tests pass a scripted/seeded
RNG and assert exact outcomes) plus the bet, and returns an `Outcome` carrying
the coins to credit on a win (0 on loss) and a human-facing detail string. The
payout multipliers bake in a ~5% house edge (see the design spec's EV table), so
over many rounds coins drain from the economy — the anti-inflation point of the
feature.
"""

import random
from dataclasses import dataclass

COINFLIP_MULT = 1.9
OVER_UNDER_MULT = 1.9
SLOTS_JACKPOT_MULT = 10
SLOTS_PAIR_MULT = 1.6
SLOTS_SYMBOLS = ["🍒", "🔔", "🍋", "⭐", "💎", "7️⃣"]


@dataclass(frozen=True)
class Outcome:
    won: bool
    payout: int  # coins credited on a win; 0 on a loss
    detail: str  # human-facing roll, e.g. "Heads", "🎲 6+4+1=11 (Over)", "🍒🍒🔔"


def play_coinflip(rng: random.Random, bet: int, choice: str) -> Outcome:
    """Coin flip. `choice` ∈ {"heads","tails"}; 50/50; a win pays bet × 1.9."""
    flip = rng.choice(["heads", "tails"])
    label = "Heads" if flip == "heads" else "Tails"
    if flip == choice:
        return Outcome(True, round(bet * COINFLIP_MULT), label)
    return Outcome(False, 0, label)


def play_over_under(rng: random.Random, bet: int, choice: str) -> Outcome:
    """Over/under dice. Sum of 3 d6; under = 3–10, over = 11–18 (P=0.5 each).
    Win pays ×1.9.

    `choice` ∈ {"over","under"}.
    """
    dice = [rng.randint(1, 6) for _ in range(3)]
    total = sum(dice)
    result = "over" if total >= 11 else "under"
    name = "Over" if result == "over" else "Under"
    detail = f"🎲 {dice[0]}+{dice[1]}+{dice[2]}={total} ({name})"
    if result == choice:
        return Outcome(True, round(bet * OVER_UNDER_MULT), detail)
    return Outcome(False, 0, detail)


def play_slots(rng: random.Random, bet: int) -> Outcome:
    """Slots. 3 reels of 6 symbols. 3-match → ×10, exactly-2-match → ×1.6, else 0."""
    reels = [rng.choice(SLOTS_SYMBOLS) for _ in range(3)]
    detail = "".join(reels)
    distinct = len(set(reels))
    if distinct == 1:
        return Outcome(True, bet * SLOTS_JACKPOT_MULT, detail)
    if distinct == 2:
        return Outcome(True, round(bet * SLOTS_PAIR_MULT), detail)
    return Outcome(False, 0, detail)
