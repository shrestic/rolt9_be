from datetime import datetime

from pydantic import BaseModel, Field


class EscalationRule(BaseModel):
    threshold: int = Field(ge=1)
    action: str  # "mute" | "ban"
    duration_seconds: int | None = None


class ModerationSettings(BaseModel):
    mod_log_channel_id: str | None = None
    dm_on_action: bool = True
    warn_escalation: list[EscalationRule] = Field(default_factory=list)


class ModCaseOut(BaseModel):
    case_number: int
    action: str
    source: str
    target_user_id: str
    target_username: str
    moderator_user_id: str
    moderator_username: str
    reason: str | None = None
    duration_seconds: int | None = None
    created_at: datetime
    active: bool


class CasesPage(BaseModel):
    items: list[ModCaseOut]
    total: int
    page: int
    page_size: int
