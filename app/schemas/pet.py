"""Pydantic schemas for the Server Pet feature (dashboard settings + status)."""

from pydantic import BaseModel, Field


class PetSettings(BaseModel):
    """Per-guild pet configuration.

    All fields have sane defaults matching the GuildPet model so GET on an
    unconfigured guild always returns a renderable object (no 404 dance).
    Constraints mirror the model's column bounds so validation happens at the
    API boundary before any DB work.
    """

    enabled: bool = False
    # min_length=1 rejects the empty string ""; max_length caps display names.
    name: str = Field(default="Pet", min_length=1, max_length=32)
    # feed_cost can be 0 (free feeding) but not negative; capped at 1M coins.
    feed_cost: int = Field(default=10, ge=0, le=1_000_000)
    # Amounts must be at least 1 (ge=1) so actions always have a visible effect.
    feed_amount: int = Field(default=30, ge=1, le=100)
    play_amount: int = Field(default=30, ge=1, le=100)
    # decay_per_day=0 means no decay (useful for testing / lax guilds).
    decay_per_day: int = Field(default=20, ge=0, le=100)


class PetStatusOut(BaseModel):
    """Read-only settled pet status for the dashboard.

    Computed by PetService.get_status() after lazy decay settlement —
    reflects what stats *would* be right now without persisting decay.
    All fields are required (no defaults) so a missing field surfaces as a
    programming error rather than a silent zero/empty.
    """

    name: str
    hunger: int
    happiness: int
    xp: int
    level: int
    stage_name: str
    stage_emoji: str
    mood_emoji: str
    # Mirrors pet.enabled so the caller never needs a second round-trip.
    enabled: bool


__all__ = ["PetSettings", "PetStatusOut"]
