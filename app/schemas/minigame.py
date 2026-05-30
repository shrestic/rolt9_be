"""Pydantic schemas for the Mini-games feature (dashboard settings).

The house edge is fixed in code (see `minigame_logic`); the only tunable knobs
are the on/off switch and the bet bounds.
"""

from pydantic import BaseModel, Field, model_validator


class MinigameSettings(BaseModel):
    """Per-guild mini-games configuration."""

    enabled: bool = False
    min_bet: int = Field(default=10, ge=1, le=1_000_000)
    max_bet: int = Field(default=10_000, ge=1, le=1_000_000_000)

    @model_validator(mode="after")
    def _check(self) -> "MinigameSettings":
        if self.min_bet > self.max_bet:
            raise ValueError("min_bet must be ≤ max_bet")
        return self


__all__ = ["MinigameSettings"]
