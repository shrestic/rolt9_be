"""Pydantic schemas for the Server Currency feature.

Covers guild-level currency configuration and wallet I/O DTOs used by
the REST API layer.  All numeric caps exist for two reasons:
  1. Overflow/inflation prevention — uncapped earn rates let a bot spam
     infinite coins, breaking the economy for every member.
  2. Relational integrity — earn_min ≤ earn_max is enforced here so the
     service layer never has to guard against an impossible range.
"""

from pydantic import BaseModel, Field, model_validator


class CurrencySettings(BaseModel):
    """Guild-level configuration for the Server Currency system.

    Validates all tuneable knobs an admin can change via the dashboard:
    - Caps on earn_min / earn_max (0–10 000) prevent runaway inflation and
      integer overflow in balance arithmetic.
    - daily_amount is capped at 1 000 000 — generous enough for any guild
      economy while staying well below int32 safe territory.
    - The model_validator enforces earn_min ≤ earn_max so the XP awarder
      can always call random.randint(earn_min, earn_max) without raising.
    - currency_name min_length=1 rejects empty strings that would render
      broken UI labels like "You earned  coins".
    """

    enabled: bool = False
    # Display name shown in bot replies and dashboard (e.g. "gold", "points").
    currency_name: str = Field(default="coins", min_length=1, max_length=32)
    # Optional emoji shown alongside the balance (e.g. "🪙", "💰").
    currency_emoji: str = Field(default="🪙", min_length=1, max_length=32)
    # Per-message earn range; both bounds share the same cap to keep math simple.
    earn_min: int = Field(default=1, ge=0, le=10_000)
    earn_max: int = Field(default=3, ge=0, le=10_000)
    # Flat amount awarded by the /daily command.
    daily_amount: int = Field(default=100, ge=0, le=1_000_000)
    # Whether members can transfer coins to each other via /pay.
    allow_pay: bool = True

    # --- Streak ---
    streak_enabled: bool = True
    # Coins added per streak day (bonus = min(streak * per_day, cap)).
    streak_bonus_per_day: int = Field(default=10, ge=0, le=10_000)
    # Ceiling on the per-day streak bonus.
    streak_bonus_cap: int = Field(default=500, ge=0, le=1_000_000)

    @model_validator(mode="after")
    def _check(self) -> "CurrencySettings":
        if self.earn_min > self.earn_max:
            raise ValueError("earn_min must be ≤ earn_max")
        return self


# --- Wallet I/O DTOs --------------------------------------------------------


class WalletMemberOut(BaseModel):
    """Single member wallet snapshot (rank + balance)."""

    user_id: str
    rank: int
    balance: int


class WalletBalanceUpdate(BaseModel):
    """Admin override payload for directly setting a member's balance."""

    # Upper cap mirrors the safe upper bound for balance storage (bigint).
    balance: int = Field(ge=0, le=1_000_000_000)


class WalletLeaderboardEntryOut(BaseModel):
    """One row of the currency leaderboard."""

    rank: int
    user_id: str
    balance: int


class WalletLeaderboardPageOut(BaseModel):
    """Paginated leaderboard response — mirrors LeaderboardPageOut in leveling."""

    items: list[WalletLeaderboardEntryOut]
    total: int
    page: int
    page_size: int


__all__ = [
    "CurrencySettings",
    "WalletBalanceUpdate",
    "WalletLeaderboardEntryOut",
    "WalletLeaderboardPageOut",
    "WalletMemberOut",
]
