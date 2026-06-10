import pytest

from app.services.ai.tools.web_search import _sanitize_query, run_read_link


@pytest.mark.asyncio
async def test_read_link_rejects_non_url():
    out = await run_read_link("this is not a link")
    assert "invalid" in out.lower()
    assert "http" in out.lower()


def test_sanitize_strips_date_from_current_query():
    # A 'current' query (containing 'today') with a stray numeric date -> drop the date
    # (avoids matching an article from a different date).
    # NOTE: the hint words (today/latest/...) are matched by _CURRENT_HINT in production (web_search.py).
    assert _sanitize_query("domestic gold price today 2/6/2026") == "domestic gold price today"
    assert _sanitize_query("breaking news today 2/6/2026 Vietnam") == "breaking news today Vietnam"
    assert _sanitize_query("USD exchange rate latest 02-06-2026") == "USD exchange rate latest"


def test_sanitize_keeps_query_without_current_hint():
    # No 'current' intent -> keep the date as-is (the user may want a specific historical date).
    q = "gold price on 1/1/2020"
    assert _sanitize_query(q) == q


def test_sanitize_noop_when_no_date():
    assert _sanitize_query("SJC gold price today") == "SJC gold price today"
