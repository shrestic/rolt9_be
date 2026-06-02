from app.services.ai.tools.web_search import _sanitize_query


def test_sanitize_strips_date_from_current_query():
    # Query 'hiện tại' (có 'hôm nay') lỡ ghép ngày số -> bỏ ngày (tránh trúng bài ngày khác).
    assert _sanitize_query("giá vàng trong nước hôm nay 2/6/2026") == "giá vàng trong nước hôm nay"
    assert _sanitize_query("tin nóng hôm nay 2/6/2026 Việt Nam") == "tin nóng hôm nay Việt Nam"
    assert _sanitize_query("tỷ giá USD mới nhất 02-06-2026") == "tỷ giá USD mới nhất"


def test_sanitize_keeps_query_without_current_hint():
    # Không có ý 'hiện tại' -> giữ nguyên ngày (có thể user muốn tra mốc lịch sử cụ thể).
    q = "giá vàng ngày 1/1/2020"
    assert _sanitize_query(q) == q


def test_sanitize_noop_when_no_date():
    assert _sanitize_query("giá vàng SJC hôm nay") == "giá vàng SJC hôm nay"
