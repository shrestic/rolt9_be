"""Subscription digest — logic thuần (test được) cho đăng ký nhận tin định kỳ.

`is_due` quyết định 'tới giờ đăng hôm nay chưa'; `build_digest_system` dựng prompt để AI
tóm tắt kết quả web search thành bản tin gọn. Việc I/O (web search, gọi AI, gửi) ở cog.
"""

from datetime import datetime

_DEFAULT_DIGEST_PERSONA = "Bạn là trợ lý tóm tắt tin tức ngắn gọn, rõ ràng bằng tiếng Việt."


def is_due(sub, now_vn: datetime) -> bool:
    """True nếu đăng ký này tới giờ đăng cho HÔM NAY mà chưa đăng.
    Bắt theo nhịp: tới hoặc qua giờ HH:MM trong ngày + chưa chạy hôm nay (last_run_on != today)."""
    if sub.last_run_on == now_vn.date():
        return False  # hôm nay đăng rồi
    return (now_vn.hour, now_vn.minute) >= (sub.hour, sub.minute)


def build_digest_system(persona: str, topic: str) -> str:
    """Prompt cho AI tóm tắt KẾT QUẢ web search về `topic` thành bản tin ngắn."""
    base = persona or _DEFAULT_DIGEST_PERSONA
    return (
        base + f"\n\nDưới đây là KẾT QUẢ TRA WEB về chủ đề '{topic}'. Hãy tóm tắt thành một bản "
        "tin NGẮN GỌN bằng tiếng Việt: 1 câu mở đầu cho biết là tin gì, rồi 3-5 gạch đầu dòng nêu "
        "điểm/số liệu chính. Nêu nguồn nếu đáng. KHÔNG bịa, KHÔNG dán link rác, không lan man."
    )
