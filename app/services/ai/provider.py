"""LLM provider abstraction — the single place that talks to the AI vendor.

v2: uses LiteLLM to call ~100 providers through one format (`acompletion`) and get the
USD cost for free (`completion_cost`). The provider is STATELESS: key/provider/model are
passed per call (per-guild, pulled from the DB), no more env-based singleton like v1.

- `AIProvider`: the interface the rest of the app depends on.
- `LiteLLMProvider`: the real one, imports litellm lazily (keeps the package optional for tests).
- `FakeAIProvider`: a deterministic stand-in for tests (no network).
- `get_ai_provider()`: returns a shared LiteLLMProvider (stateless -> safe to share).
"""

import logging
from dataclasses import dataclass
from typing import Protocol

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AICompletion:
    """One model response + tokens + USD cost (for the per-guild budget)."""

    text: str
    input_tokens: int
    output_tokens: int
    cost_usd: float  # from litellm.completion_cost(); 0.0 if it can't be computed
    tool_calls: list[dict] | None = (
        None  # [{id, name, arguments(str json)}] when the model calls a tool
    )
    raw_message: dict | None = (
        None  # assistant message (with tool_calls) to append back into messages
    )


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
        allow_empty: bool = False,
    ) -> AICompletion: ...


class FakeAIProvider:
    """Deterministic provider for tests — never touches the network."""

    available = True  # kept for back-compat with old tests; gateway v2 doesn't use it

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
        # turns: a multi-turn script for tool-calling tests, each element is
        # {"tool_calls": [...]} or {"text": "..."}; each complete() pops one element.
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
        allow_empty: bool = False,
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
    """The real provider. Imports litellm lazily; key/model passed per-call (per-guild)."""

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
        allow_empty: bool = False,
    ) -> AICompletion:
        import litellm  # lazy — keeps the package optional for tests/keyless deploys

        _register_custom_prices(litellm)
        # If `messages` is already supplied (tool-calling loop), use it as-is; else build from system/history/prompt.
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
            # Under heavy load -> DeepSeek often 429s/times-out briefly; retry so we don't spit ❌ at the user.
            "num_retries": 2,
            # Cap per call so one hung call doesn't hold a DB connection forever (drains the pool under load).
            "timeout": 90,
        }
        if tools:
            kwargs["tools"] = tools
        resp = await litellm.acompletion(**kwargs)
        # completion_cost may raise/return 0 for unknown models — wrap it, fall back to 0.0.
        try:
            cost = float(litellm.completion_cost(resp))
        except Exception:  # noqa: BLE001 — don't let a cost-calc error break the request
            log.warning("litellm.completion_cost failed for %s/%s", provider, model)
            cost = 0.0
        usage = resp.usage
        message = resp.choices[0].message

        # Model called a tool -> return tool_calls + raw_message (to append into messages for the next step).
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
        # A reasoning model burned all its tokens on reasoning -> empty content. Single-shot (welcome/roast…)
        # has NO fallback, so raise a clear (actionable) error. The tool-calling loop (allow_empty=True)
        # must NOT throw: return text="" so ToolRunner degrades gracefully ("give it another go") instead of
        # spewing a technical error.
        if not content and getattr(message, "reasoning_content", None) and not allow_empty:
            raise ValueError(
                "The model used up all its tokens on reasoning before it could answer — "
                "bump AI_MAX_TOKENS or pick a non-reasoning model."
            )
        # Ordinary empty content: do NOT raise here — return text="" and let the caller decide
        # (gateway.complete single-shot will raise; the tool loop falls back gently).
        return AICompletion(
            text=content,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            cost_usd=cost,
        )


# Custom prices for litellm models NOT yet in the built-in price table (too new),
# so completion_cost() can compute USD → the budget guard works. Unit: USD / 1
# token (= price_per_1M / 1_000_000). Source: DeepSeek pricing, May 2026
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
    """Load custom prices into litellm once (idempotent). On error -> skip, don't crash."""
    global _prices_registered
    if _prices_registered:
        return
    try:
        litellm.register_model(_CUSTOM_PRICES)
        _prices_registered = True
    except Exception:  # noqa: BLE001 — missing prices just make cost=0, must not break the call
        log.warning("litellm.register_model failed for custom prices")


_provider: AIProvider | None = None


def get_ai_provider() -> AIProvider:
    """Return a process-wide shared LiteLLMProvider (stateless, so safe to share).

    Keeps the old function name so the 5 cogs (roast/summarizer/ask/chat/welcome) don't have to change.
    """
    global _provider
    if _provider is None:
        _provider = LiteLLMProvider()
    return _provider
