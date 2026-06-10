"""Provider/model whitelist for AI v2.

The SINGLE source of truth: it both validates the PUT settings input (blocking
unsupported models) and feeds the FE dropdown via the /ai/catalog endpoint. Adding
a new model = editing this file (a deliberate trade-off for control + validation —
see spec section 9).

Model names must match the format LiteLLM understands after joining "provider/model"
(e.g. "anthropic/claude-haiku-4-5"). The list below is a starting point, tweak it once
you've confirmed it works in practice with LiteLLM.
"""

# provider key -> {display label, model list for the dropdown}
# Provider key must match the LiteLLM name (joined as "provider/model" when called).
# Latest models updated via web search — May 2026. If a model has a "-latest" alias,
# prefer the alias (it auto-points to the newest version, no code changes needed).
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
        # Cheapest of this bunch.
        #   - deepseek-chat: NON-thinking — fast, cheap, answers right away (GREAT for a
        #     roast/chat/summarize bot). NOTE: DeepSeek retires this alias on 2026-07-24.
        #   - deepseek-v4-flash / v4-pro: have "thinking" (reasoning) — slower,
        #     burn tokens on reasoning; need a generous AI_MAX_TOKENS or you get empty replies.
        "label": "DeepSeek",
        "models": ["deepseek-chat", "deepseek-v4-flash", "deepseek-v4-pro"],
    },
    "groq": {
        # Blazing-fast inference, generous free tier. gpt-oss models use the "openai/..." form.
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
    """True when (provider, model) is in the whitelist."""
    return provider in AI_CATALOG and model in AI_CATALOG[provider]["models"]
