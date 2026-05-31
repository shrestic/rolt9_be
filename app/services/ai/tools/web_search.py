"""Tool web_search — Tavily (key global). Không mạng nếu thiếu key. Lỗi -> chuỗi, không raise."""

import logging

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)


async def run_web_search(query: str) -> str:
    if not settings.TAVILY_API_KEY:
        return "Web search chưa cấu hình (thiếu TAVILY_API_KEY)."
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                "https://api.tavily.com/search",
                json={"api_key": settings.TAVILY_API_KEY, "query": query, "max_results": 3},
            )
            r.raise_for_status()
            data = r.json()
    except Exception:  # noqa: BLE001 — lỗi tra web không được làm hỏng request
        log.warning("web_search failed for query=%r", query)
        return "Tra web thất bại."
    results = data.get("results") or []
    if not results:
        return "Không tìm thấy kết quả."
    return "\n".join(
        f"- {x.get('title', '?')} ({x.get('url', '')})\n  {x.get('content', '')[:300]}"
        for x in results
    )
