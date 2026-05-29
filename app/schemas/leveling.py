from pydantic import BaseModel, Field, model_validator

from app.core.colors import ColorValidation, RankCardColors
from app.core.enums import BgType, LevelRoleMode, NotificationMode


class LevelingSettings(BaseModel):
    enabled: bool = False
    xp_min: int = Field(default=15, ge=1, le=1000)
    xp_max: int = Field(default=25, ge=1, le=1000)
    cooldown_seconds: int = Field(default=60, ge=10, le=600)
    min_message_length: int = Field(default=4, ge=1, le=2000)
    ignore_emoji_only: bool = True
    ignore_link_only: bool = True
    ignored_channel_ids: list[str] = Field(default_factory=list)
    ignored_role_ids: list[str] = Field(default_factory=list)
    notification_mode: NotificationMode = NotificationMode.CHANNEL
    notification_channel_id: str | None = None
    level_role_mode: LevelRoleMode = LevelRoleMode.REPLACING
    xp_decay_enabled: bool = False
    xp_decay_percent: int = Field(default=10, ge=1, le=100)
    xp_decay_inactivity_days: int = Field(default=7, ge=1)

    @model_validator(mode="after")
    def _check(self) -> "LevelingSettings":
        if self.xp_min > self.xp_max:
            raise ValueError("xp_min must be ≤ xp_max")
        # Only enforce channel-id requirement when leveling is actually enabled.
        # Admins can stage `mode='channel'` with a NULL channel before enabling.
        if (
            self.enabled
            and self.notification_mode == NotificationMode.CHANNEL
            and self.notification_channel_id is None
        ):
            raise ValueError(
                "notification_channel_id is required when notification_mode = 'channel' and enabled = true"
            )
        return self


class LeaderboardEntryOut(BaseModel):
    rank: int
    user_id: str
    total_xp: int
    level: int


class LeaderboardPageOut(BaseModel):
    items: list[LeaderboardEntryOut]
    total: int
    page: int
    page_size: int


class MemberXpOut(BaseModel):
    user_id: str
    rank: int
    level: int
    total_xp: int
    xp_into_level: int
    xp_for_next_level: int


class MemberXpUpdate(BaseModel):
    total_xp: int = Field(ge=0)


class LevelRewardOut(BaseModel):
    level: int
    role_id: str


class LevelRewardCreate(BaseModel):
    level: int = Field(ge=1, le=500)
    # Snowflake — validated as all-digit decimal string so the endpoint's
    # `int(payload.role_id)` can't surface a ValueError. Looser than the
    # canonical 17-20 digit form so test fixtures still apply.
    role_id: str = Field(pattern=r"^\d+$")


class RankCardThemeIO(BaseModel):
    bg_type: BgType = BgType.GRADIENT
    bg_color_1: str = Field(
        default=RankCardColors.DEFAULT_BG_PRIMARY,
        pattern=ColorValidation.HEX_COLOR_PATTERN,
    )
    bg_color_2: str = Field(
        default=RankCardColors.DEFAULT_BG_SECONDARY,
        pattern=ColorValidation.HEX_COLOR_PATTERN,
    )
    accent_color: str = Field(
        default=RankCardColors.DEFAULT_ACCENT,
        pattern=ColorValidation.HEX_COLOR_PATTERN,
    )
    text_color: str = Field(
        default=RankCardColors.DEFAULT_TEXT,
        pattern=ColorValidation.HEX_COLOR_PATTERN,
    )


__all__ = [
    "LeaderboardEntryOut",
    "LeaderboardPageOut",
    "LevelRewardCreate",
    "LevelRewardOut",
    "LevelingSettings",
    "MemberXpOut",
    "MemberXpUpdate",
    "RankCardThemeIO",
]
