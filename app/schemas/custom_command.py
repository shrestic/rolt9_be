from pydantic import BaseModel, Field, field_validator, model_validator


class EmbedSpec(BaseModel):
    title: str | None = None
    description: str | None = None
    color: str | None = None  # hex like "#5865F2"
    image_url: str | None = None
    footer: str | None = None


class CustomCommandIn(BaseModel):
    trigger: str = Field(min_length=1, max_length=64)
    response_type: str = "text"  # "text" | "embed"
    response_text: str | None = None
    embed: EmbedSpec | None = None
    allowed_role_ids: list[str] = Field(default_factory=list)
    allowed_channel_ids: list[str] = Field(default_factory=list)
    cooldown_seconds: int = Field(default=0, ge=0)
    enabled: bool = True

    @field_validator("trigger")
    @classmethod
    def _single_word_lower(cls, v: str) -> str:
        v = v.strip().lower()
        if not v or " " in v:
            raise ValueError("trigger must be a single word with no spaces")
        return v

    @model_validator(mode="after")
    def _require_response(self) -> "CustomCommandIn":
        if self.response_type not in ("text", "embed"):
            raise ValueError("response_type must be 'text' or 'embed'")
        if self.response_type == "text" and not self.response_text:
            raise ValueError("response_text is required when response_type is 'text'")
        if self.response_type == "embed" and self.embed is None:
            raise ValueError("embed is required when response_type is 'embed'")
        return self


class CustomCommandOut(BaseModel):
    id: str
    trigger: str
    response_type: str
    response_text: str | None = None
    embed: EmbedSpec | None = None
    allowed_role_ids: list[str]
    allowed_channel_ids: list[str]
    cooldown_seconds: int
    enabled: bool


class CommandSettings(BaseModel):
    prefix: str = Field(default="!", min_length=1, max_length=5)
    enabled: bool = True


# ─────────────────────────────────────────────────────────────────────────
# Live-preview schemas (POST /{guild_id}/commands/preview)
# ─────────────────────────────────────────────────────────────────────────


class PlaceholderInfo(BaseModel):
    # Name as it appears between { and } in templates.
    name: str
    description: str
    # The value used for this placeholder in the current preview render,
    # so the admin can see exactly what each one expands to.
    example: str


class CommandPreviewRequest(BaseModel):
    # Reuses the same shape as CustomCommandIn for the response portion only,
    # so the FE can hand the in-progress form straight to /preview.
    response_type: str = "text"
    response_text: str | None = None
    embed: EmbedSpec | None = None


class RenderedEmbed(BaseModel):
    # The post-substitution embed. Color is the resolved int (after the
    # blurple fallback) so the FE doesn't need to repeat the hex parse.
    title: str | None = None
    description: str | None = None
    color: int
    footer: str | None = None
    image_url: str | None = None


class CommandPreviewResponse(BaseModel):
    # Exactly one of rendered_text / rendered_embed will be set, matching
    # the response_type in the request.
    rendered_text: str | None = None
    rendered_embed: RenderedEmbed | None = None
    # Every placeholder the bot understands, plus the value used in this render.
    placeholders: list[PlaceholderInfo]
