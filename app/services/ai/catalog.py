"""Whitelist provider/model cho AI v2.

Nguồn sự thật DUY NHẤT: vừa validate input PUT settings (chặn model không hỗ trợ),
vừa feed dropdown cho FE qua endpoint /ai/catalog. Thêm model mới = sửa file này
(chấp nhận đánh đổi để có kiểm soát + validate — xem spec mục 9).

Tên model phải đúng định dạng LiteLLM hiểu sau khi ghép "provider/model"
(vd "anthropic/claude-haiku-4-5"). Danh sách dưới là điểm khởi đầu, chỉnh khi
xác nhận thực tế với LiteLLM.
"""

# provider key -> {label hiển thị, danh sách model cho dropdown}
AI_CATALOG: dict[str, dict] = {
    "anthropic": {
        "label": "Claude (Anthropic)",
        "models": ["claude-haiku-4-5", "claude-sonnet-4-6"],
    },
    "openai": {
        "label": "OpenAI",
        "models": ["gpt-4o-mini", "gpt-4o"],
    },
    "gemini": {
        "label": "Google Gemini",
        "models": ["gemini-2.0-flash", "gemini-2.0-pro"],
    },
    "groq": {
        "label": "Groq",
        "models": ["llama-3.3-70b-versatile"],
    },
}


def is_valid(provider: str, model: str) -> bool:
    """True khi (provider, model) nằm trong whitelist."""
    return provider in AI_CATALOG and model in AI_CATALOG[provider]["models"]
