"""Tool web_search — Tavily (key global). Không mạng nếu thiếu key. Lỗi -> chuỗi, không raise."""

import logging
import re

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)

# Query hỏi tin/giá HIỆN TẠI (có các từ này) mà model lỡ ghép NGÀY SỐ -> bỏ ngày, vì search dễ
# trúng bài NGÀY KHÁC (vd '6/2' khi định '2/6') cho giá CŨ/SAI. Lưới chốt cứng ở code: prompt đã
# dặn model đừng ghép ngày, nhưng LLM không tất định nên vẫn lọt -> code dọn nốt.
_CURRENT_HINT = re.compile(r"hôm nay|hiện tại|mới nhất|bây giờ|\bgiờ\b", re.IGNORECASE)
_DATE_TOKEN = re.compile(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b")


def _sanitize_query(query: str) -> str:
    """Bỏ ngày số khỏi query 'hiện tại' (query không có ý hiện tại -> giữ nguyên, vẫn tra mốc cũ được)."""
    if _CURRENT_HINT.search(query):
        cleaned = re.sub(r"\s{2,}", " ", _DATE_TOKEN.sub("", query)).strip()
        if cleaned:
            return cleaned
    return query


async def run_web_search(query: str) -> str:
    if not settings.TAVILY_API_KEY:
        return "Web search chưa cấu hình (thiếu TAVILY_API_KEY)."
    query = _sanitize_query(query)
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
