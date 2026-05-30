"""Pydantic schemas for the AI feature (dashboard settings + usage readout)."""

from pydantic import BaseModel, Field


class AISettings(BaseModel):
    """Per-guild AI configuration (input for PUT)."""

    enabled: bool = False
    monthly_token_budget: int = Field(default=100_000, ge=0, le=100_000_000)


class AISettingsOut(AISettings):
    """Settings + the current month's token usage (for GET / PUT response)."""

    tokens_used_this_month: int = 0


__all__ = ["AISettings", "AISettingsOut"]
