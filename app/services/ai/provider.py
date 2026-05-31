"""LLM provider abstraction — nơi duy nhất nói chuyện với vendor AI.

v2: dùng LiteLLM để gọi ~100 provider cùng một format (`acompletion`) và lấy chi
phí USD sẵn (`completion_cost`). Provider STATELESS: key/provider/model truyền theo
từng lần gọi (per-guild, lấy từ DB), không còn singleton-theo-env như v1.

- `AIProvider`: interface phần còn lại của app phụ thuộc.
- `LiteLLMProvider`: thật, import litellm lazily (giữ package optional cho test).
- `FakeAIProvider`: stand-in tất định cho test (không mạng).
- `get_ai_provider()`: trả LiteLLMProvider dùng chung (stateless -> share an toàn).
"""

import logging
from dataclasses import dataclass
from typing import Protocol

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AICompletion:
    """Một phản hồi model + token + chi phí USD (cho budget per-guild)."""

    text: str
    input_tokens: int
    output_tokens: int
    cost_usd: float  # từ litellm.completion_cost(); 0.0 nếu không tính được
    tool_calls: list[dict] | None = None  # [{id, name, arguments(str json)}] khi model gọi tool
    raw_message: dict | None = None  # assistant message (kèm tool_calls) để nối vào messages


class AIProvider(Protocol):
    async def complete(
        self,
        *,
        provider: str,
        model: str,
        api_key: str,
        system: str,
        prompt: str,
        max_tokens: int,
        history: list[dict] | None = None,
        messages: list[dict] | None = None,
        tools: list[dict] | None = None,
    ) -> AICompletion: ...


class FakeAIProvider:
    """Provider tất định cho test — không bao giờ chạm mạng."""

    available = True  # giữ cho back-compat với test cũ; gateway v2 không dùng

    def __init__(
        self,
        text: str = "(fake)",
        input_tokens: int = 10,
        output_tokens: int = 20,
        cost_usd: float = 0.001,
        turns: list[dict] | None = None,
    ):
        self._text = text
        self._in = input_tokens
        self._out = output_tokens
        self._cost = cost_usd
        # turns: kịch bản nhiều lượt cho tool-calling test, mỗi phần tử là
        # {"tool_calls": [...]} hoặc {"text": "..."}; mỗi complete() lấy 1 phần tử.
        self._turns = list(turns) if turns else None

    async def complete(
        self,
        *,
        provider: str,
        model: str,
        api_key: str,
        system: str,
        prompt: str,
        max_tokens: int,
        history: list[dict] | None = None,
        messages: list[dict] | None = None,
        tools: list[dict] | None = None,
    ) -> AICompletion:
        if self._turns:
            turn = self._turns.pop(0)
            if "tool_calls" in turn:
                tcs = turn["tool_calls"]
                return AICompletion(
                    text="",
                    input_tokens=self._in,
                    output_tokens=self._out,
                    cost_usd=self._cost,
                    tool_calls=tcs,
                    raw_message={
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": t["id"],
                                "type": "function",
                                "function": {"name": t["name"], "arguments": t["arguments"]},
                            }
                            for t in tcs
                        ],
                    },
                )
            return AICompletion(
                text=turn["text"],
                input_tokens=self._in,
                output_tokens=self._out,
                cost_usd=self._cost,
            )
        return AICompletion(
            text=self._text,
            input_tokens=self._in,
            output_tokens=self._out,
            cost_usd=self._cost,
        )


class LiteLLMProvider:
    """Provider thật. Import litellm lazily; key/model truyền per-call (per-guild)."""

    async def complete(
        self,
        *,
        provider: str,
        model: str,
        api_key: str,
        system: str,
        prompt: str,
        max_tokens: int,
        history: list[dict] | None = None,
        messages: list[dict] | None = None,
        tools: list[dict] | None = None,
    ) -> AICompletion:
        import litellm  # lazy — giữ package optional cho test/deploy không key

        _register_custom_prices(litellm)
        # `messages` truyền sẵn (vòng tool-calling) thì dùng nguyên; else dựng từ system/history/prompt.
        if messages is None:
            messages = [{"role": "system", "content": system}]
            if history:
                messages.extend(history)
            messages.append({"role": "user", "content": prompt})
        kwargs = {
            "model": f"{provider}/{model}",
            "api_key": api_key,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
        resp = await litellm.acompletion(**kwargs)
        # completion_cost có thể raise/trả 0 với model lạ — bọc lại, fallback 0.0.
        try:
            cost = float(litellm.completion_cost(resp))
        except Exception:  # noqa: BLE001 — không để lỗi tính tiền làm hỏng request
            log.warning("litellm.completion_cost failed for %s/%s", provider, model)
            cost = 0.0
        usage = resp.usage
        message = resp.choices[0].message

        # Model gọi tool -> trả tool_calls + raw_message (để nối vào messages cho bước sau).
        raw_tool_calls = getattr(message, "tool_calls", None)
        if raw_tool_calls:
            tool_calls = [
                {"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments}
                for tc in raw_tool_calls
            ]
            raw_message = {
                "role": "assistant",
                "content": message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in raw_tool_calls
                ],
            }
            return AICompletion(
                text="",
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                cost_usd=cost,
                tool_calls=tool_calls,
                raw_message=raw_message,
            )

        content = (message.content or "").strip()
        # Reasoning model tiêu hết token cho suy luận -> báo lỗi rõ (actionable).
        if not content and getattr(message, "reasoning_content", None):
            raise ValueError(
                "Model dùng hết token cho phần suy luận mà chưa kịp trả lời — "
                "tăng AI_MAX_TOKENS hoặc chọn model không-reasoning."
            )
        # Content rỗng-thường: KHÔNG raise ở đây — trả text="" để caller quyết
        # (gateway.complete single-shot sẽ raise; vòng tool sẽ fallback nhẹ nhàng).
        return AICompletion(
            text=content,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            cost_usd=cost,
        )


# Giá custom cho model litellm CHƯA có trong bảng giá built-in (model quá mới),
# để completion_cost() tính được USD → budget guard hoạt động. Đơn vị: USD / 1
# token (= giá_per_1M / 1_000_000). Nguồn: DeepSeek pricing, tháng 5/2026
# (flash $0.14/$0.28, pro $0.435/$0.87 per 1M cache-miss in/out).
_CUSTOM_PRICES = {
    "deepseek/deepseek-v4-flash": {
        "input_cost_per_token": 0.14 / 1_000_000,
        "output_cost_per_token": 0.28 / 1_000_000,
        "litellm_provider": "deepseek",
        "mode": "chat",
    },
    "deepseek/deepseek-v4-pro": {
        "input_cost_per_token": 0.435 / 1_000_000,
        "output_cost_per_token": 0.87 / 1_000_000,
        "litellm_provider": "deepseek",
        "mode": "chat",
    },
}

_prices_registered = False


def _register_custom_prices(litellm) -> None:
    """Nạp giá custom vào litellm một lần (idempotent). Lỗi -> bỏ qua, không crash."""
    global _prices_registered
    if _prices_registered:
        return
    try:
        litellm.register_model(_CUSTOM_PRICES)
        _prices_registered = True
    except Exception:  # noqa: BLE001 — thiếu giá chỉ làm cost=0, không được làm hỏng call
        log.warning("litellm.register_model failed for custom prices")


_provider: AIProvider | None = None


def get_ai_provider() -> AIProvider:
    """Trả LiteLLMProvider dùng chung process-wide (stateless nên share an toàn).

    Giữ tên hàm cũ để 5 cog (roast/summarizer/ask/chat/welcome) không phải đổi.
    """
    global _provider
    if _provider is None:
        _provider = LiteLLMProvider()
    return _provider
