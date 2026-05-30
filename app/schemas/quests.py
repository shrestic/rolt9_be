"""Pydantic schemas for quests (dashboard CRUD)."""

from typing import Literal

from pydantic import BaseModel, Field

Period = Literal["daily", "weekly"]
ObjectiveType = Literal["earn_coins", "daily_claim"]


class QuestIn(BaseModel):
    """Create/update payload for a quest definition."""

    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=255)
    period: Period
    objective_type: ObjectiveType
    target: int = Field(ge=1, le=100_000)
    reward_coins: int = Field(ge=0, le=1_000_000)
    enabled: bool = True


class QuestOut(BaseModel):
    """A quest definition as returned to the dashboard."""

    id: str
    name: str
    description: str | None
    period: str
    objective_type: str
    target: int
    reward_coins: int
    enabled: bool


__all__ = ["ObjectiveType", "Period", "QuestIn", "QuestOut"]
