"""LLM provider abstraction — the only place that talks to an AI vendor.

`AIProvider` is the interface the rest of the app depends on; `AnthropicAIProvider`
is the real Claude implementation (it imports the `anthropic` SDK lazily so tests
and key-less deploys don't need the package), and `FakeAIProvider` is a
deterministic stand-in for tests (no network). `get_ai_provider()` returns a
process-wide singleton built from settings.
"""

from dataclasses import dataclass
from typing import Protocol

from app.core.config import settings


@dataclass(frozen=True)
class AICompletion:
    """One model response + token accounting (for the per-guild budget)."""

    text: str
    input_tokens: int
    output_tokens: int


class AIProvider(Protocol):
    @property
    def available(self) -> bool:
        """True when the provider is configured enough to call (e.g. has a key)."""
        ...

    async def complete(self, *, system: str, prompt: str, max_tokens: int) -> AICompletion: ...


class FakeAIProvider:
    """Deterministic provider for tests — never touches the network."""

    available = True

    def __init__(self, text: str = "(fake)", input_tokens: int = 10, output_tokens: int = 20):
        self._text = text
        self._in = input_tokens
        self._out = output_tokens

    async def complete(self, *, system: str, prompt: str, max_tokens: int) -> AICompletion:
        return AICompletion(text=self._text, input_tokens=self._in, output_tokens=self._out)


class AnthropicAIProvider:
    """Real Claude provider. Imports the anthropic SDK lazily (only when calling)."""

    def __init__(self, api_key: str, model: str):
        self._key = api_key
        self._model = model

    @property
    def available(self) -> bool:
        return bool(self._key)

    async def complete(self, *, system: str, prompt: str, max_tokens: int) -> AICompletion:
        import anthropic  # lazy — keep the package optional for tests/key-less deploys

        client = anthropic.AsyncAnthropic(api_key=self._key)
        msg = await client.messages.create(
            model=self._model,
            system=system,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        # Concatenate the text blocks of the response (ignore any non-text blocks).
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        return AICompletion(
            text=text.strip(),
            input_tokens=msg.usage.input_tokens,
            output_tokens=msg.usage.output_tokens,
        )


_provider: AIProvider | None = None


def get_ai_provider() -> AIProvider:
    """Process-wide singleton built from settings (Anthropic; unavailable if no key)."""
    global _provider
    if _provider is None:
        _provider = AnthropicAIProvider(settings.ANTHROPIC_API_KEY, settings.AI_MODEL)
    return _provider
