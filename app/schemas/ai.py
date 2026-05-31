"""Pydantic schemas cho AI v2 (settings BYO-key + usage token/cost)."""

from decimal import Decimal

from pydantic import BaseModel, Field


class AISettings(BaseModel):
    """Cấu hình AI per-guild — input cho PUT.

    `api_key` ghi-một-chiều: None = giữ nguyên key cũ, "" = xóa key, "sk-..." = đặt mới.
    """

    enabled: bool = False
    provider: str = ""
    model: str = ""
    monthly_budget_usd: Decimal = Field(default=Decimal("5"), ge=0, le=1000)
    persona: str = Field(default="", max_length=2000)
    api_key: str | None = None


class AISettingsOut(BaseModel):
    """Settings + usage tháng này — response GET/PUT. KHÔNG bao giờ trả key thật."""

    enabled: bool
    provider: str
    model: str
    monthly_budget_usd: Decimal
    persona: str
    has_key: bool
    key_hint: str = ""  # 4 ký tự cuối của key, "" nếu chưa có
    tokens_used_this_month: int = 0
    cost_used_this_month: Decimal = Decimal("0")


class KbEntryIn(BaseModel):
    """Create payload cho một mục knowledge-base."""

    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=2000)


class KbEntryOut(BaseModel):
    """Một mục knowledge-base trả cho dashboard."""

    id: str
    title: str
    content: str


__all__ = ["AISettings", "AISettingsOut", "KbEntryIn", "KbEntryOut"]
