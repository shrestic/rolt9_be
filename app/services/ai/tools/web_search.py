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


# Số kết quả lấy NỘI DUNG ĐẦY ĐỦ + giới hạn ký tự mỗi bài (snippet 300 ký tự thường thiếu ->
# luôn KÈM raw_content top kết quả để AI trả lời CHÍNH XÁC, vd giá vàng lấy từ bảng giá trong bài).
_SEARCH_DEEP_N = 2
_SEARCH_DEEP_CAP = 3000


async def run_web_search(query: str) -> str:
    if not settings.TAVILY_API_KEY:
        return "Web search chưa cấu hình (thiếu TAVILY_API_KEY)."
    query = _sanitize_query(query)
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": settings.TAVILY_API_KEY,
                    "query": query,
                    "max_results": 3,
                    # LUÔN kèm extract: lấy nội dung đầy đủ bài, không chỉ snippet ngắn.
                    "include_raw_content": True,
                },
            )
            r.raise_for_status()
            data = r.json()
    except Exception:  # noqa: BLE001 — lỗi tra web không được làm hỏng request
        log.warning("web_search failed for query=%r", query)
        return "Tra web thất bại."
    results = data.get("results") or []
    if not results:
        return "Không tìm thấy kết quả."
    # Danh sách snippet (tất cả) + NỘI DUNG ĐẦY ĐỦ của top kết quả (để trả lời chuẩn số liệu).
    out = ["Kết quả tìm kiếm:"]
    for x in results:
        out.append(
            f"- {x.get('title', '?')} ({x.get('url', '')})\n  {(x.get('content') or '')[:300]}"
        )
    for x in results[:_SEARCH_DEEP_N]:
        raw = (x.get("raw_content") or "").strip()
        if raw:
            out.append(
                f"\nNội dung đầy đủ — {x.get('title', '?')} ({x.get('url', '')}):\n"
                f"{raw[:_SEARCH_DEEP_CAP]}"
            )
    return "\n".join(out)


_READ_LINK_CAP = 6000  # cắt nội dung trang để AI tóm tắt, đỡ ngốn token


async def run_read_link(url: str) -> str:
    """Đọc nội dung 1 URL -> text sạch để AI tóm tắt/trả lời.

    Tavily /extract trước (tái dùng key đã có). Lỗi/rỗng/hết credit -> fallback Jina Reader
    (r.jina.ai, FREE, không cần key). Hỏng cả hai -> báo nhẹ, KHÔNG raise.
    """
    url = (url or "").strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return "Link không hợp lệ (cần bắt đầu bằng http/https)."
    # 1) Tavily extract — bóc nội dung sạch, tái dùng key.
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
        except Exception:  # noqa: BLE001 — lỗi/hết credit -> thử fallback, không raise
            log.warning("read_link: tavily extract failed for %r", url)
    # 2) Fallback Jina Reader — FREE, không key.
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            r = await client.get(f"https://r.jina.ai/{url}")
            r.raise_for_status()
            if r.text.strip():
                return r.text[:_READ_LINK_CAP]
    except Exception:  # noqa: BLE001
        log.warning("read_link: jina reader failed for %r", url)
    return "Đọc link không được (trang chặn bot hoặc lỗi mạng) — thử link khác nhé."
