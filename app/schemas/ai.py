"""Pydantic schemas for AI v2 (BYO-key settings + token/cost usage)."""

from decimal import Decimal

from pydantic import BaseModel, Field


class AISettings(BaseModel):
    """Per-guild AI config — input for PUT.

    `api_key` is write-only: None = keep the existing key, "" = clear the key, "sk-..." = set a new one.
    """

    enabled: bool = False
    provider: str = ""
    model: str = ""
    monthly_budget_usd: Decimal = Field(default=Decimal("5"), ge=0, le=1000)
    persona: str = Field(default="", max_length=2000)
    agent_enabled: bool = False
    agent_channel_id: str | None = None
    tools_enabled: bool = True
    actions_enabled: bool = False
    companion_enabled: bool = False
    companion_channel_id: str | None = None
    companion_cooldown_min: int = Field(default=45, ge=5, le=1440)
    api_key: str | None = None


class AISettingsOut(BaseModel):
    """Settings + this month's usage — GET/PUT response. NEVER returns the real key."""

    enabled: bool
    provider: str
    model: str
    monthly_budget_usd: Decimal
    persona: str
    agent_enabled: bool
    agent_channel_id: str | None = None
    tools_enabled: bool
    actions_enabled: bool
    companion_enabled: bool
    companion_channel_id: str | None = None
    companion_cooldown_min: int
    has_key: bool
    key_hint: str = ""  # last 4 characters of the key, "" if none yet
    tokens_used_this_month: int = 0
    cost_used_this_month: Decimal = Decimal("0")


class KbEntryIn(BaseModel):
    """Create payload for a knowledge-base entry."""

    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=2000)


class KbEntryOut(BaseModel):
    """A knowledge-base entry returned to the dashboard."""

    id: str
    title: str
    content: str


__all__ = ["AISettings", "AISettingsOut", "KbEntryIn", "KbEntryOut"]
