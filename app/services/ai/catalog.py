"""Whitelist provider/model cho AI v2.

Nguồn sự thật DUY NHẤT: vừa validate input PUT settings (chặn model không hỗ trợ),
vừa feed dropdown cho FE qua endpoint /ai/catalog. Thêm model mới = sửa file này
(chấp nhận đánh đổi để có kiểm soát + validate — xem spec mục 9).

Tên model phải đúng định dạng LiteLLM hiểu sau khi ghép "provider/model"
(vd "anthropic/claude-haiku-4-5"). Danh sách dưới là điểm khởi đầu, chỉnh khi
xác nhận thực tế với LiteLLM.
"""

# provider key -> {label hiển thị, danh sách model cho dropdown}
# Provider key phải đúng tên LiteLLM (ghép "provider/model" khi gọi).
# Cập nhật model mới nhất qua web search — tháng 5/2026. Model có alias "-latest"
# thì ưu tiên dùng alias (tự trỏ bản mới, khỏi sửa code).
AI_CATALOG: dict[str, dict] = {
    "anthropic": {
        "label": "Claude (Anthropic)",
        "models": ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5"],
    },
    "openai": {
        "label": "OpenAI",
        "models": ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano", "o4-mini"],
    },
    "gemini": {
        "label": "Google Gemini",
        "models": [
            "gemini-3.1-pro",
            "gemini-3.5-flash",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
        ],
    },
    "deepseek": {
        # Rẻ nhất nhóm này.
        #   - deepseek-chat: NON-thinking — nhanh, rẻ, trả lời ngay (HỢP cho bot
        #     roast/chat/summarize). LƯU Ý: alias này DeepSeek dừng 24/07/2026.
        #   - deepseek-v4-flash / v4-pro: có "thinking" (reasoning) — chậm hơn,
        #     tốn token suy luận; cần AI_MAX_TOKENS rộng kẻo trả về rỗng.
        "label": "DeepSeek",
        "models": ["deepseek-chat", "deepseek-v4-flash", "deepseek-v4-pro"],
    },
    "groq": {
        # Inference siêu nhanh, free tier rộng. gpt-oss model có dạng "openai/...".
        "label": "Groq",
        "models": [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
        ],
    },
    "mistral": {
        "label": "Mistral",
        "models": [
            "mistral-large-latest",
            "mistral-medium-latest",
            "mistral-small-latest",
            "magistral-medium-latest",
        ],
    },
    "xai": {
        "label": "xAI Grok",
        "models": ["grok-4.3", "grok-4.20-0309-non-reasoning"],
    },
}


def is_valid(provider: str, model: str) -> bool:
    """True khi (provider, model) nằm trong whitelist."""
    return provider in AI_CATALOG and model in AI_CATALOG[provider]["models"]
