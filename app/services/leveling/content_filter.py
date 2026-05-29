"""Anti-spam content filter for incoming chat messages.

When a member sends a message, we don't want to reward every keystroke —
that's how MEE6 ends up with leaderboards dominated by emoji spammers.
This module decides "is this message *real* enough to earn XP?" using
three independent gates that the guild admin can toggle individually:

1. **Minimum length** — reject very short messages ("k", "lol", "👍").
2. **Emoji-only** — reject messages that are just emoji decoration
   (custom Discord emoji + Unicode emoji ranges).
3. **Link-only** — reject messages that are nothing but a URL
   (anchored regex, so "check this https://…" still counts as real).

The module is **stateless and pure** — it takes the message text and a
`FilterConfig` dataclass and returns a boolean. No DB, no Discord object,
no logging side effects. That keeps testing trivial: pass strings, assert
booleans.

The `FilterConfig` mirrors the subset of `GuildLevelingConfig` that this
filter actually reads. We pass that subset (rather than the ORM row) so
tests can drive the filter without building or mocking a full DB record.
"""

import re
from dataclasses import dataclass

# Matches Discord's custom emoji syntax: <:name:id> and the animated form
# <a:name:id>. These never collapse to a single Unicode char so the
# unicode-emoji regex below wouldn't catch them.
_CUSTOM_EMOJI = re.compile(r"<a?:[A-Za-z0-9_]+:\d+>")

# Approximate Unicode emoji ranges (Misc Symbols, Supplemental Symbols, etc.).
# This is intentionally *approximate* — it covers the common ranges plus the
# ZWJ + variation selector chars that show up in compound emoji. A handful
# of false positives is fine because we only use it to decide whether the
# message is "emoji-only" after stripping all emoji-shaped tokens.
_UNICODE_EMOJI = re.compile(
    r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F900-\U0001F9FF"
    r"\U0001F600-\U0001F64F\U0001F680-\U0001F6FF‍️]"
)

# Anchored URL pattern. The leading `^` + trailing `$` are critical: we want
# "https://example.com" to match, but "see https://example.com for context"
# to *not* match. The regex deliberately doesn't try to validate domain
# shapes — we only need to recognise a bare link.
_URL = re.compile(r"^https?://\S+/?$", re.IGNORECASE)


@dataclass(frozen=True)
class FilterConfig:
    """Subset of guild leveling settings the content filter needs.

    Decoupled from `GuildLevelingConfig` (the SQLAlchemy ORM model) so this
    module doesn't have to import the model — and so tests can build a
    config inline without database setup.

    Attributes:
        min_message_length: Reject messages whose stripped text length is
            shorter than this. A typical value is 4 (rejects "lol", "ok",
            "k", but accepts "hello"). Set to 1 to effectively disable.
        ignore_emoji_only: If True, messages that contain *nothing but*
            emoji (custom or Unicode) are rejected.
        ignore_link_only: If True, messages that are *exactly* a single
            URL (no surrounding text) are rejected.
    """

    min_message_length: int
    ignore_emoji_only: bool
    ignore_link_only: bool


def _is_emoji_only(content: str) -> bool:
    """Return True if `content` collapses to whitespace after stripping emoji.

    Strips both custom Discord emoji (`<:name:id>`) and Unicode emoji ranges
    one after the other. If anything non-whitespace is left, the message
    has real text content and isn't emoji-only.

    Args:
        content: The raw message text. Leading/trailing whitespace is OK;
            the function `.strip()`s the result before checking.

    Returns:
        True for messages like "🎉🎉🎉" or "<:hype:123> 👍", False for
        messages like "🎉 nice", "hello", or "" (empty after strip
        is still "not emoji-only" by convention — empty short messages
        are caught by the min-length gate elsewhere).
    """
    stripped = _CUSTOM_EMOJI.sub("", content)
    stripped = _UNICODE_EMOJI.sub("", stripped)
    return stripped.strip() == ""


def _is_link_only(content: str) -> bool:
    """Return True if `content` (stripped) is exactly one URL and nothing else.

    Uses `re.match` against an anchored pattern. The pattern requires the
    URL to occupy the entire message after `.strip()`.

    Args:
        content: The raw message text.

    Returns:
        True for "https://example.com" or "https://example.com/",
        False for "look at https://example.com" or "https://a.com b.com".
    """
    return _URL.match(content.strip()) is not None


def should_award(content: str, config: FilterConfig) -> bool:
    """Decide whether this message qualifies for XP.

    Runs three independent gates in order; the first failure short-circuits.
    A message must pass *every* enabled gate to qualify.

    Order of checks (cheapest first):
        1. Length gate (`min_message_length`). Always runs.
        2. Emoji-only gate, if `ignore_emoji_only` is True.
        3. Link-only gate, if `ignore_link_only` is True.

    Args:
        content: The raw message text from Discord. The function `.strip()`s
            internally, so leading/trailing whitespace doesn't help users
            game the min-length check.
        config: Filter knobs sourced from the guild's leveling config.

    Returns:
        True when the message should earn XP; False when any gate rejects
        it. The caller (XpAwarder) is responsible for the cooldown gate —
        this function only judges content shape.

    Example:
        >>> cfg = FilterConfig(min_message_length=4, ignore_emoji_only=True,
        ...                    ignore_link_only=True)
        >>> should_award("hello there", cfg)
        True
        >>> should_award("k", cfg)           # too short
        False
        >>> should_award("🎉🎉🎉", cfg)        # emoji-only
        False
        >>> should_award("https://x.com", cfg)  # link-only
        False
    """
    text = content.strip()

    # Gate 1: length. Cheapest check, runs unconditionally.
    if len(text) < config.min_message_length:
        return False

    # Gate 2: emoji-only. Skipped when the admin turned it off so people
    # *can* farm XP via emoji if the server's culture is fine with it.
    if config.ignore_emoji_only and _is_emoji_only(text):
        return False

    # Gate 3: link-only. Same opt-out semantics as gate 2.
    if config.ignore_link_only and _is_link_only(text):
        return False

    return True
