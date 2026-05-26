# Pure logic shared by:
#   - the bot cog (renders responses when a user types a custom-command prefix)
#   - the dashboard preview endpoint (renders the same content with sample data
#     so admins can see what their command will look like before saving)
#
# Keeping the rules and registries in one place ensures the bot and the
# dashboard can never drift out of sync — adding a placeholder here makes it
# show up live in both places.

from collections.abc import Iterable
from dataclasses import dataclass

from app.discord_io.types import Embed, EmbedField

# ─────────────────────────────────────────────────────────────────────────────
# Placeholder registry
# ─────────────────────────────────────────────────────────────────────────────


# One row in the placeholder registry. `example` is the value used by the
# preview endpoint so admins can see exactly what each placeholder expands to
# in the current guild context.
@dataclass(frozen=True)
class PlaceholderDef:
    name: str
    description: str


# All placeholders the bot understands inside custom-command response text /
# embed fields. The dashboard fetches this list to show admins what's allowed.
PLACEHOLDERS: list[PlaceholderDef] = [
    PlaceholderDef("user", "The user's display name (e.g. Alice)."),
    PlaceholderDef("user.mention", "Raw @mention of the user (pings them)."),
    PlaceholderDef("server", "The current server's name."),
    PlaceholderDef("member_count", "Number of members in the server."),
]


# ─────────────────────────────────────────────────────────────────────────────
# Template rendering
# ─────────────────────────────────────────────────────────────────────────────


def build_context(
    *,
    user_display: str,
    user_mention: str,
    server_name: str,
    member_count: int,
) -> dict[str, str]:
    """Build the substitution context for one render. Same shape for cog
    runtime and dashboard preview — only the source of the values differs."""
    return {
        "user": user_display,
        "user.mention": user_mention,
        "server": server_name,
        "member_count": str(member_count),
    }


def render_template(text: str, context: dict[str, str]) -> str:
    """Replace {key} placeholders from context; unknown placeholders are left as-is."""
    result = text
    for key, value in context.items():
        result = result.replace("{" + key + "}", str(value))
    return result


# Discord blurple — used as fallback when the admin enters an invalid hex.
_DEFAULT_COLOR = 0x5865F2


def parse_color(color_hex: str | None) -> int:
    """Convert "#5865F2" → 0x5865F2. Garbage in → blurple default."""
    if not color_hex:
        return _DEFAULT_COLOR
    try:
        return int(color_hex.lstrip("#"), 16)
    except ValueError:
        return _DEFAULT_COLOR


def render_embed_spec(spec: dict, context: dict[str, str]) -> Embed:
    """Build an Embed (our dataclass) from an admin-supplied spec dict,
    substituting placeholders in title / description / footer."""
    fields: list[EmbedField] = []  # custom-command embeds don't yet expose fields
    return Embed(
        title=render_template(spec["title"], context) if spec.get("title") else None,
        description=(
            render_template(spec["description"], context) if spec.get("description") else None
        ),
        color=parse_color(spec.get("color")),
        fields=fields,
        footer=render_template(spec["footer"], context) if spec.get("footer") else None,
        image_url=spec.get("image_url"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Permission + cooldown helpers (unchanged — kept here for backwards-compat)
# ─────────────────────────────────────────────────────────────────────────────


def is_allowed(
    *,
    member_role_ids: Iterable[int],
    channel_id: int,
    allowed_role_ids: list[int],
    allowed_channel_ids: list[int],
) -> bool:
    """Empty allow-lists mean unrestricted. Otherwise membership must match."""
    if allowed_channel_ids and channel_id not in allowed_channel_ids:
        return False
    if allowed_role_ids and not (set(member_role_ids) & set(allowed_role_ids)):
        return False
    return True


def is_on_cooldown(*, last_used: float | None, cooldown_seconds: int, now: float) -> bool:
    if cooldown_seconds <= 0 or last_used is None:
        return False
    return (now - last_used) < cooldown_seconds
