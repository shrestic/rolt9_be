"""Reminder service — prompt cho "smart reminder" (tách khỏi cog để test được).

Khi reminder có `task`, tới giờ scheduler tra web (run_web_search) rồi nhờ AI trả lời
THẬT theo kết quả đó. `build_reminder_task_system` dựng system prompt cho bước AI này:
trả lời thẳng vào việc, kèm số liệu cụ thể, ngắn gọn.
"""

# Persona mặc định nếu guild chưa đặt — giữ giọng bot, đỡ trả lời khô khan.
_DEFAULT_PERSONA = "Bạn là rolt9 — trợ lý Discord người Việt, nói chuyện tự nhiên, thẳng thắn."


def build_reminder_task_system(persona: str, task: str) -> str:
    """System prompt cho lượt AI trả lời smart reminder.

    persona = giọng bot của guild (rỗng -> mặc định). task = thứ người dùng hẹn tra
    (vd 'giá vàng hôm nay'). Prompt người dùng sẽ là KẾT QUẢ web search thô.
    """
    base = (persona or "").strip() or _DEFAULT_PERSONA
    return (
        f"{base}\n"
        f"Người dùng đã HẸN bạn tới giờ này thì tra cứu và báo: '{task}'. "
        "Dưới đây là KẾT QUẢ web search mới nhất. Hãy trả lời THẲNG vào việc bằng tiếng Việt, "
        "NGẮN GỌN, KÈM SỐ LIỆU/CHI TIẾT cụ thể nếu có (giá, mốc thời gian, nguồn). "
        "Nếu kết quả không đủ rõ, nói thật là chưa chắc — ĐỪNG bịa số."
    )
