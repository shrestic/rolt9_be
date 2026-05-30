"""Pydantic schemas for the AI feature (dashboard settings + usage readout)."""

from pydantic import BaseModel, Field


class AISettings(BaseModel):
    """Per-guild AI configuration (input for PUT)."""

    enabled: bool = False
    monthly_token_budget: int = Field(default=100_000, ge=0, le=100_000_000)
    persona: str = Field(default="", max_length=500)


class AISettingsOut(AISettings):
    """Settings + the current month's token usage (for GET / PUT response)."""

    tokens_used_this_month: int = 0


class KbEntryIn(BaseModel):
    """Create payload for a knowledge-base entry."""

    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=2000)


class KbEntryOut(BaseModel):
    """A knowledge-base entry as returned to the dashboard."""

    id: str
    title: str
    content: str


__all__ = ["AISettings", "AISettingsOut", "KbEntryIn", "KbEntryOut"]
