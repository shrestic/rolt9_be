"""Render member rank cards as PNG images.

Used by the `/rank` slash command and by the (future) dashboard preview.
The output is a PNG byte string ready to attach to a Discord message:

    ┌────────────────────────────────────────────────────────────┐
    │ Alice                                       RANK #3        │
    │                                                            │
    │ LEVEL 12   XP 1,420                                        │
    │                                                            │
    │ [██████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░]            │
    │ 270 / 540 XP                                               │
    └────────────────────────────────────────────────────────────┘
                       (CARD_WIDTH × CARD_HEIGHT = 800 × 240)

Two background styles, picked by the guild's `bg_type` setting:

    SOLID    → single colour fill (bg_color_1).
    GRADIENT → horizontal linear gradient from bg_color_1 → bg_color_2.

Why no `IMAGE` mode (anymore): URL-fetched backgrounds were expensive
(HTTP per render, whitelist policy, font/codec edge cases) and rarely
used in practice. The column and enum value were removed; bring them
back through a migration if the dashboard ever needs them.

Threading model:

    The Pillow draw is CPU-bound. If we ran it inline in the event loop,
    a single `/rank` call would freeze the bot's gateway and the FastAPI
    HTTP loop for the duration of the draw (~10-50 ms on a real box, but
    worse under load). Instead, `RankCardRenderer.render_async` wraps the
    sync draw in `asyncio.to_thread`, offloading it to the default thread
    pool. The event loop stays responsive; only one worker thread is busy.
"""

import asyncio
import io
import logging
from dataclasses import dataclass
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from app.core.colors import RankCardColors
from app.core.enums import BgType

log = logging.getLogger(__name__)

# Card dimensions. Matches Discord's preferred embed image aspect ratio
# closely enough that the result doesn't get auto-resized on display.
CARD_WIDTH = 800
CARD_HEIGHT = 240


@dataclass(frozen=True)
class RankCardData:
    """Per-member data the renderer needs to draw one card.

    Decoupled from the ORM intentionally: this dataclass has no DB ties,
    so the renderer is a pure draw function. `LevelingService.build_rank_card_data`
    is responsible for shaping the DB row into this struct.

    Attributes:
        username: Display name to print on the card. Whatever string the
            caller has handy (Discord display name, OAuth username, etc.).
        rank: 1-indexed position in the guild leaderboard. Shown as
            "RANK #N" in the header.
        level: Current level.
        total_xp: Cumulative XP. Shown formatted with thousands separators.
        xp_into_level: How much XP they've earned *into* the current level.
            Used as the progress-bar numerator.
        xp_for_next_level: How much XP the current level costs in total.
            Used as the progress-bar denominator.
    """

    username: str
    rank: int
    level: int
    total_xp: int
    xp_into_level: int
    xp_for_next_level: int


@dataclass(frozen=True)
class RankCardTheme:
    """Per-guild visual palette for the rank card.

    Loaded from `guild_rank_card_theme` (or the bot's hardcoded default
    when a guild hasn't customised). Colours are hex strings matching the
    regex `^#[0-9a-fA-F]{6}$` (the Pydantic schema enforces that), so the
    renderer trusts them without re-validating.

    Attributes:
        bg_type: SOLID or GRADIENT. Picks the background drawing path.
        bg_color_1: Primary background colour (the only one for SOLID).
        bg_color_2: Secondary colour, used as the gradient end colour.
            Unused for SOLID but still stored so admins can toggle modes
            without losing their second colour.
        accent_color: Progress-bar fill colour.
        text_color: Text + empty-progress-bar colour.
    """

    bg_type: BgType
    bg_color_1: str
    bg_color_2: str
    accent_color: str
    text_color: str


@lru_cache(maxsize=1)
def _load_font(size: int = 28) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Return a Pillow font, cached because the same sizes repeat per render.

    Tries the bundled DejaVu Sans Bold first (we install it in the production
    Dockerfile so non-Latin characters render correctly). If the file isn't
    present — typical for unit-test environments — falls back to Pillow's
    built-in default font (ASCII only, but never crashes).

    Args:
        size: Font size in points. We use a few distinct sizes per render
            (36 for header, 22 for body, 16 for the XP caption). Each gets
            its own cached `ImageFont` instance.

    Returns:
        A Pillow `ImageFont` instance, usable in `draw.text(...)` calls.
    """
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert "#rrggbb" to an (r, g, b) tuple of 0-255 ints.

    The schema-level regex (`^#[0-9a-fA-F]{6}$`) already guarantees the
    format, so we don't re-validate here — invalid input would have been
    rejected before reaching the renderer.

    Args:
        hex_color: A 7-character hex string, e.g. "#0f172a".

    Returns:
        Tuple `(r, g, b)` with each component in 0-255.

    Example:
        >>> _hex_to_rgb("#0f172a")
        (15, 23, 42)
    """
    s = hex_color.lstrip("#")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def _make_background(theme: RankCardTheme) -> Image.Image:
    """Build the background `Image` for the rank card.

    Two paths, picked by `theme.bg_type`:

        SOLID    → one colour fill. Fast: a single `Image.new` call.
        GRADIENT → manual per-column linear interpolation between
                   `bg_color_1` (left edge) and `bg_color_2` (right edge).
                   We hand-write the gradient (~O(width * height) pixel
                   writes) rather than using a third-party library to
                   keep dependencies minimal. ~5-10 ms on a real box.

    Args:
        theme: Theme to draw from. Only the bg_* fields are read here.

    Returns:
        A Pillow RGB `Image` of size (CARD_WIDTH, CARD_HEIGHT), ready to
        have text drawn on top.
    """
    c1 = _hex_to_rgb(theme.bg_color_1)

    # SOLID: one constant colour for the whole canvas.
    if theme.bg_type == BgType.SOLID:
        return Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), c1)

    # GRADIENT: interpolate per-column from c1 to c2.
    c2 = _hex_to_rgb(theme.bg_color_2)
    img = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), c1)
    pixels = img.load()  # Direct pixel access — much faster than `putpixel` in a loop.
    for x in range(CARD_WIDTH):
        # `t` is the 0..1 progress across the card width. Multiply each
        # channel difference by `t` and add to c1 → straight linear ramp.
        t = x / (CARD_WIDTH - 1)
        r = int(c1[0] + (c2[0] - c1[0]) * t)
        g = int(c1[1] + (c2[1] - c1[1]) * t)
        b = int(c1[2] + (c2[2] - c1[2]) * t)
        # Same colour down the column → cheap vertical sweep.
        for y in range(CARD_HEIGHT):
            pixels[x, y] = (r, g, b)
    return img


def _render_sync(data: RankCardData, theme: RankCardTheme) -> bytes:
    """Draw the rank card and return its PNG bytes.

    This is the actual draw routine. Called from a worker thread by
    `RankCardRenderer.render_async`, so it must be sync — no `await`,
    no asyncio primitives.

    Steps:
        1. Build the background.
        2. Open a `Draw` context on it.
        3. Stamp four pieces of text: username, "RANK #N", level/XP line,
           and the XP caption under the progress bar.
        4. Stroke the empty progress bar (rounded rectangle, semi-transparent).
        5. Stroke the filled portion in `accent_color`, length proportional
           to `xp_into_level / xp_for_next_level`.
        6. Encode as PNG into a `BytesIO` and return the bytes.

    Args:
        data: Per-member shaped data.
        theme: Per-guild visual palette.

    Returns:
        PNG bytes. The PNG signature is `b"\\x89PNG\\r\\n\\x1a\\n"` — tests
        assert on this to verify output is actually a PNG.
    """
    img = _make_background(theme)
    draw = ImageDraw.Draw(img)

    # Hex-to-rgb the text/accent colours once up front (cheap, but no point
    # converting per draw call).
    text_rgb = _hex_to_rgb(theme.text_color)
    accent_rgb = _hex_to_rgb(theme.accent_color)

    # Three font sizes total. `_load_font` is `lru_cache`d so repeated calls
    # with the same size are free.
    font_big = _load_font(36)
    font_med = _load_font(22)
    font_small = _load_font(16)

    # Header row: username on the left, "RANK #N" on the right.
    draw.text((40, 40), data.username, fill=text_rgb, font=font_big)
    draw.text(
        (CARD_WIDTH - 160, 50),
        f"RANK #{data.rank}",
        fill=text_rgb,
        font=font_med,
    )

    # Body row: level + cumulative XP. We format with thousands separators
    # because high-XP numbers get long fast (e.g. 1,420,000).
    draw.text(
        (40, 100),
        f"LEVEL {data.level}   XP {data.total_xp:,}",
        fill=text_rgb,
        font=font_med,
    )

    # Progress bar geometry. Hardcoded coordinates because the card size is
    # fixed; if you change CARD_WIDTH/CARD_HEIGHT, re-tune these too.
    bar_x, bar_y, bar_w, bar_h = 40, 160, CARD_WIDTH - 80, 24

    # Empty bar (semi-transparent white). Drawn first so the fill paints on top.
    draw.rounded_rectangle(
        (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h),
        radius=12,
        fill=RankCardColors.PROGRESS_BAR_EMPTY_RGBA,
    )

    # Fill width = current level progress as a fraction. Clamped to [0, 1]
    # in case of weird data (e.g. xp_into_level > xp_for_next_level due to
    # admin overrides; we still don't want the bar to extend past the end).
    if data.xp_for_next_level > 0:
        pct = max(0.0, min(1.0, data.xp_into_level / data.xp_for_next_level))
    else:
        # `xp_for_next_level` is theoretically always positive (the formula
        # is `5*L^2 + 50*L + 100`), but defend anyway — empty bar is the
        # right answer if math ever went sideways.
        pct = 0.0
    fill_w = int(bar_w * pct)

    # Only stroke the filled portion if there *is* one — Pillow chokes on
    # zero-width rounded rectangles.
    if fill_w > 0:
        draw.rounded_rectangle(
            (bar_x, bar_y, bar_x + fill_w, bar_y + bar_h),
            radius=12,
            fill=accent_rgb,
        )

    # Caption directly under the bar, e.g. "270 / 540 XP".
    draw.text(
        (bar_x, bar_y + bar_h + 6),
        f"{data.xp_into_level:,} / {data.xp_for_next_level:,} XP",
        fill=text_rgb,
        font=font_small,
    )

    # Serialise to PNG bytes via an in-memory buffer.
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


class RankCardRenderer:
    """Async-safe facade for the sync Pillow draw.

    The only thing this class adds over `_render_sync` is the
    `asyncio.to_thread` hop. We keep it as a class (not a free function)
    so DI factories can pass it around as a dependency that's easy to
    mock in tests (e.g. swap in a renderer that returns canned bytes).
    """

    async def render_async(self, data: RankCardData, theme: RankCardTheme) -> bytes:
        """Render the card on a worker thread and return PNG bytes.

        Why a worker thread: the Pillow draw is pure-Python + C-extension
        code that *does not* yield to the event loop. Calling `_render_sync`
        directly would freeze the gateway and the HTTP server for the
        duration of the draw. `asyncio.to_thread` puts it on the default
        thread pool, where the GIL releases around the C calls and the
        event loop stays responsive.

        Args:
            data: Per-member data (rank, level, XP figures, username).
            theme: Per-guild palette.

        Returns:
            PNG bytes ready to send to Discord via
            `discord.File(BytesIO(bytes), filename="rank.png")`.

        Example:
            >>> renderer = RankCardRenderer()
            >>> png = await renderer.render_async(data, theme)
            >>> png[:8]
            b'\\x89PNG\\r\\n\\x1a\\n'
        """
        return await asyncio.to_thread(_render_sync, data, theme)
