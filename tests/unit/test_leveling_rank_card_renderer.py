import asyncio

import pytest

from app.services.leveling.rank_card_renderer import (
    RankCardData,
    RankCardRenderer,
    RankCardTheme,
)


@pytest.mark.asyncio
async def test_render_returns_png_bytes():
    renderer = RankCardRenderer()
    data = RankCardData(
        username="alice",
        rank=1,
        level=5,
        total_xp=600,
        xp_into_level=100,
        xp_for_next_level=255,
    )
    theme = RankCardTheme(
        bg_type="solid",
        bg_color_1="#0f172a",
        bg_color_2="#581c87",
        accent_color="#fbbf24",
        text_color="#ffffff",
    )
    png = await renderer.render_async(data, theme)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.asyncio
async def test_render_gradient_does_not_raise():
    renderer = RankCardRenderer()
    data = RankCardData(
        username="alice",
        rank=12,
        level=15,
        total_xp=3250,
        xp_into_level=400,
        xp_for_next_level=1100,
    )
    theme = RankCardTheme(
        bg_type="gradient",
        bg_color_1="#0f172a",
        bg_color_2="#581c87",
        accent_color="#fbbf24",
        text_color="#ffffff",
    )
    png = await renderer.render_async(data, theme)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.asyncio
async def test_render_runs_off_event_loop():
    renderer = RankCardRenderer()
    data = RankCardData(
        username="alice",
        rank=1,
        level=1,
        total_xp=120,
        xp_into_level=20,
        xp_for_next_level=155,
    )
    theme = RankCardTheme(
        bg_type="solid",
        bg_color_1="#000000",
        bg_color_2="#000000",
        accent_color="#fbbf24",
        text_color="#ffffff",
    )

    progress = {"ticks": 0}

    async def tick():
        for _ in range(5):
            await asyncio.sleep(0.001)
            progress["ticks"] += 1

    tick_task = asyncio.create_task(tick())
    await renderer.render_async(data, theme)
    await tick_task
    assert progress["ticks"] == 5
