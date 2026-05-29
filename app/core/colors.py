"""Global color palette for the entire codebase.

Single source of truth for every brand colour, action colour, default
palette and validation regex used across the bot, the HTTP API and the
rank-card renderer. If a tweak is needed (rebrand, accessibility audit,
dark-mode fork) you change it once here and every consumer follows.

Why `app/core/` and not `app/models/` or `app/services/...`:

    `app/core/` is the bottom of the dependency graph — it only imports
    from itself. That makes it safe for models, schemas, services, bot
    cogs and HTTP endpoints to all import from here without ever risking
    a circular import.

Layout:

    DiscordBrand         — Discord's own brand colours (blurple, etc.).
                           Used as a fallback / neutral default by code
                           that doesn't have a domain-specific accent.

    RankCardColors       — Leveling feature: rank-card defaults, embed
                           accent for `/leaderboard` and `/level-rewards`,
                           and the renderer's progress-bar overlay tuple.

    ModerationColors     — Per-action accent colours for moderation case
                           embeds (ban / kick / mute / unmute / unban / warn).
                           Picked to make the mod-log visually scannable.

    ColorValidation      — Regex used by Pydantic schemas to validate
                           user-supplied hex colors.

Important non-rule:

    The Alembic migrations that create columns with `server_default='#xxxxxx'`
    deliberately hardcode the hex strings. Migrations are frozen historical
    snapshots — if a constant here ever changes, replaying the old migration
    must still produce the old default, otherwise re-running history would
    diverge. The trade-off is a small bit of duplication for migration
    correctness.
"""


class DiscordBrand:
    """Discord's own brand colours, exposed as ints for `discord.Embed(color=…)`.

    These are what discord.py reaches for when no app-specific colour is
    set. We expose them as named constants so code that wants the brand
    blurple as a fallback (e.g. custom commands without a configured
    colour) doesn't have to hardcode the magic number.

    Constants:
        BLURPLE: Discord's primary brand purple. Default for any embed
            that doesn't override.
    """

    BLURPLE = 0x5865F2


class RankCardColors:
    """Rank-card palette + the `/leaderboard` / `/level-rewards` embed accent.

    Every value is the *default* — guilds that customise their theme via
    `PUT /leveling/rank-card-theme` use the persisted values from
    `guild_rank_card_theme` instead, and the renderer never sees these
    constants for those guilds.

    Constants:
        DEFAULT_BG_PRIMARY: Dark blue-purple. Left edge of the gradient
            (and the sole fill for SOLID mode).
        DEFAULT_BG_SECONDARY: Lighter purple. Right edge of the gradient.
            Stored even for SOLID mode so admins can flip modes without
            losing their second colour.
        DEFAULT_ACCENT: Amber. Used for the progress-bar fill on the
            rank card and the embed accent on `/leaderboard` /
            `/level-rewards`.
        DEFAULT_TEXT: Pure white. Used for all text on the card.
        DEFAULT_ACCENT_INT: Same as DEFAULT_ACCENT but as an int —
            discord.py's `Embed(color=…)` wants an int, not a string.
            Paired with DEFAULT_ACCENT; keep them in sync.
        PROGRESS_BAR_EMPTY_RGBA: 4-tuple painted under the progress bar
            before the accent overlay. Semi-transparent white so the
            empty portion of the bar is visible against any background.
    """

    DEFAULT_BG_PRIMARY = "#0f172a"
    DEFAULT_BG_SECONDARY = "#581c87"
    DEFAULT_ACCENT = "#fbbf24"
    DEFAULT_TEXT = "#ffffff"

    # Integer mirror of DEFAULT_ACCENT for discord.py's `Embed(color=…)` API.
    # Update both together if you change the accent.
    DEFAULT_ACCENT_INT = 0xFBBF24

    # RGBA tuple. Pillow expects a 4-tuple here even though the canvas is
    # RGB — the alpha is honoured by `rounded_rectangle` for blending.
    PROGRESS_BAR_EMPTY_RGBA = (255, 255, 255, 60)


class ModerationColors:
    """Per-action accent colours for moderation case embeds.

    Used by `build_case_embed` to colour the side bar of each mod-log
    entry. Picked so a moderator scanning the channel can spot bans
    (red) vs. warnings (yellow) at a glance.

    Constants:
        BAN: Discord danger red (Brand Red).
        KICK: Strong orange. Less severe than ban but still punitive.
        MUTE: Yellow-orange. Temporary, restrictive but reversible.
        UNMUTE: Discord brand green. Indicates revert / positive action.
        UNBAN: Same green as UNMUTE — both undo an enforcement action.
        WARN: Light yellow. Soft warning, lowest severity.
        FALLBACK: Discord blurple — used when the action name doesn't
            match any of the above (defensive default).
    """

    BAN = 0xED4245
    KICK = 0xE67E22
    MUTE = 0xFAA61A
    UNMUTE = 0x57F287
    UNBAN = 0x57F287
    WARN = 0xFEE75C
    FALLBACK = DiscordBrand.BLURPLE

    @classmethod
    def for_action(cls, action: str) -> int:
        """Map a mod-action string to its accent colour, falling back to BLURPLE.

        Args:
            action: One of "ban", "kick", "mute", "unmute", "unban", "warn".
                Anything else returns FALLBACK so the embed still renders.

        Returns:
            The matching int colour, ready to pass to `Embed(color=…)`.
        """
        return _MOD_ACTION_COLORS.get(action, cls.FALLBACK)


# Lookup table built once at import time. Kept outside the class so the
# classmethod above can read it without touching `cls.__dict__` directly.
_MOD_ACTION_COLORS = {
    "ban": ModerationColors.BAN,
    "kick": ModerationColors.KICK,
    "mute": ModerationColors.MUTE,
    "unmute": ModerationColors.UNMUTE,
    "unban": ModerationColors.UNBAN,
    "warn": ModerationColors.WARN,
}


class ColorValidation:
    """Validation regexes for user-supplied colours.

    Used by Pydantic `Field(..., pattern=…)` declarations so the renderer
    and downstream code can trust their inputs without re-validating.

    Constants:
        HEX_COLOR_PATTERN: 6-digit hex with a leading `#`. Case-insensitive
            (the renderer's parser lowercases before `int(s, 16)`).
    """

    HEX_COLOR_PATTERN = r"^#[0-9a-fA-F]{6}$"
