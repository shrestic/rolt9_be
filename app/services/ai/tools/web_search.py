"""Tool web_search — Tavily (global key). No network if key missing. On error -> string, never raises."""

import logging
import re

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)

# Query asking for CURRENT news/prices (containing these words) where the model accidentally
# appended a NUMERIC DATE -> strip the date, because search easily hits an article from a
# DIFFERENT date (e.g. '6/2' when '2/6' was meant) giving STALE/WRONG prices. Hard backstop in
# code: the prompt already tells the model not to append a date, but the LLM isn't deterministic
# so some still slip through -> code cleans up the rest.
_CURRENT_HINT = re.compile(r"\btoday\b|\bnow\b|\blatest\b|\bcurrent\b|\brecent\b", re.IGNORECASE)
_DATE_TOKEN = re.compile(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b")


def _sanitize_query(query: str) -> str:
    """Strip numeric dates from a 'current' query (queries with no current intent -> kept as-is, can still look up older dates)."""
    if _CURRENT_HINT.search(query):
        cleaned = re.sub(r"\s{2,}", " ", _DATE_TOKEN.sub("", query)).strip()
        if cleaned:
            return cleaned
    return query


# Number of results to pull FULL CONTENT for + per-article char cap (a 300-char snippet is often
# too short -> always INCLUDE raw_content of the top results so the AI answers ACCURATELY, e.g.
# gold prices read from a price table inside the article).
_SEARCH_DEEP_N = 2
_SEARCH_DEEP_CAP = 3000


async def run_web_search(query: str) -> str:
    if not settings.TAVILY_API_KEY:
        return "Web search not configured (missing TAVILY_API_KEY)."
    query = _sanitize_query(query)
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": settings.TAVILY_API_KEY,
                    "query": query,
                    "max_results": 3,
                    # ALWAYS include extract: pull the full article content, not just a short snippet.
                    "include_raw_content": True,
                },
            )
            r.raise_for_status()
            data = r.json()
    except Exception:  # noqa: BLE001 — a web-search error must not break the request
        log.warning("web_search failed for query=%r", query)
        return "Web search failed."
    results = data.get("results") or []
    if not results:
        return "No results found."
    # List of snippets (all) + FULL CONTENT of the top results (to answer figures accurately).
    out = ["Search results:"]
    for x in results:
        out.append(
            f"- {x.get('title', '?')} ({x.get('url', '')})\n  {(x.get('content') or '')[:300]}"
        )
    for x in results[:_SEARCH_DEEP_N]:
        raw = (x.get("raw_content") or "").strip()
        if raw:
            out.append(
                f"\nFull content — {x.get('title', '?')} ({x.get('url', '')}):\n"
                f"{raw[:_SEARCH_DEEP_CAP]}"
            )
    return "\n".join(out)


_READ_LINK_CAP = 6000  # truncate page content for the AI to summarize, to save tokens


async def run_read_link(url: str) -> str:
    """Read the content of a single URL -> clean text for the AI to summarize/answer.

    Tavily /extract first (reuses the existing key). On error/empty/out-of-credit -> fall back to
    Jina Reader (r.jina.ai, FREE, no key needed). If both fail -> a soft message, NEVER raises.
    """
    url = (url or "").strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return "Invalid link (must start with http/https)."
    # 1) Tavily extract — pulls clean content, reuses the key.
    if settings.TAVILY_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                r = await client.post(
                    "https://api.tavily.com/extract",
                    json={"api_key": settings.TAVILY_API_KEY, "urls": [url]},
                )
                r.raise_for_status()
                res = r.json().get("results") or []
                content = res[0].get("raw_content") if res else ""
                if content and content.strip():
                    return content[:_READ_LINK_CAP]
        except Exception:  # noqa: BLE001 — error/out-of-credit -> try fallback, don't raise
            log.warning("read_link: tavily extract failed for %r", url)
    # 2) Fallback Jina Reader — FREE, no key.
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            r = await client.get(f"https://r.jina.ai/{url}")
            r.raise_for_status()
            if r.text.strip():
                return r.text[:_READ_LINK_CAP]
    except Exception:  # noqa: BLE001
        log.warning("read_link: jina reader failed for %r", url)
    return "Couldn't read the link (the page blocks bots or a network error) — try another link."
