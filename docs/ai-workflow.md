# AI Layer — Guide & Workflow

Shared AI foundation layer + 4 features: **Roast, Summarize, Q&A (Ask), Personality (Chat)**.

> **v2 (BYO-key multi-provider — 2026-05-31):** each server **enters its own API key**, **picks a provider/model** (Anthropic/OpenAI/Gemini/Groq via **LiteLLM**), and the budget is measured in **USD/month** (no longer tokens). Migration `b4c5d6e7f8a9`. See section 4. **After deploying v2, admins must go to the dashboard and re-enter their API key + reset the budget** (the unit switched token→USD, default $5; AI stays off until a key is set).

---

## 1. Overview

- The bot calls the LLM through a **shared gateway** (`AIGateway`) → **LiteLLM** (calls ~100 providers in the same format, computes USD cost automatically).
- **Servers pay their own way** with their **own API key** (stored Fernet-encrypted in the DB, no fallback to a global key). Each server has a **USD/month cap** to bound spend.
- All 4 features plug into the gateway: `/roast`, `/summarize`, `/ask`, `/chat` (the gateway signature is unchanged between v1→v2).

---

## 2. For admins — Dashboard → server → AI

| Field | Meaning | Default |
|---|---|---|
| **Enable AI** | Turn all AI on/off for the server | off |
| **Provider** | Anthropic / OpenAI / Gemini / Groq (from the catalog) | "" |
| **Model** | A model belonging to the chosen provider (e.g. `claude-haiku-4-5`, `gpt-4o-mini`) | "" |
| **API key** | The server's key, Fernet-encrypted. GET only returns `has_key` + the last 4 characters; the key is never exposed. Leave blank = keep the existing key, send "" = delete it | — |
| **Budget USD/month** | USD/month spend cap (UTC). Exceeded → AI refuses until next month | 5.0 |
| **Bot persona** | Personality for `/chat` (empty = default friendly) | "" |
| **Knowledge base** | List of FAQ entries (title + content) for `/ask` — add/remove on the dashboard | — |
| *(display)* | "This month: X tokens ≈ $Y / $Z budget" | — |

**Operation:** missing key/provider/model → AI reports "not configured" (no crash). The global `ANTHROPIC_API_KEY` is **deprecated** (no longer the primary path, the gateway does not fall back). `TOKEN_ENCRYPTION_KEY` must be set to encrypt the guild key.

---

## 3. For members — Discord commands

| Command | What it does |
|---|---|
| `/roast <member>` | AI roasts a member (playful, no heavy insults). 10s cooldown |
| `/summarize [count]` | Summarizes the channel's last N messages (default 30, max 100). 15s cooldown |
| `/ask <question>` | Answers based on the **knowledge base** the server admin loaded; outside the base → "no information yet". 10s cooldown |
| `/chat <message>` | Chats with the bot using the server's **persona**. 8s cooldown |

- AI off / missing key / monthly quota exhausted → ❌ a gentle notice. Roast blocks bots/self-roast.

---

## 4. Internals (for devs)

```
Feature (e.g. /roast) → RoastService → AIGateway.complete(guild, system, prompt)
   ├─ guild registered? AI enabled? has api_key_enc + provider + model? monthly USD cost < budget?
   ├─ decrypt_str(api_key_enc) → provider.complete(provider, model, api_key, ...) → LiteLLM
   └─ record tokens (input+output) + cost_usd into ai_usage for the current month
```

- **`AIProvider`** (provider.py): stateless protocol — `complete(*, provider, model, api_key, system, prompt, max_tokens)`. `LiteLLMProvider` (real, lazy-imports `litellm`, uses `litellm.acompletion` + `litellm.completion_cost`; cost error → 0.0 + log, no crash) + `FakeAIProvider` (test, no network calls, returns a fake cost). `get_ai_provider()` = singleton `LiteLLMProvider()` (stateless so safe to share; key/model passed per-call).
- **`AIGateway`**: the single chokepoint — checks **enabled + (key/provider/model) + USD budget** before spending money, decrypts the key, calls the provider, records tokens + cost. Every AI feature plugs in here (decoupled, never calling each other).
- **Catalog** (`catalog.py`): whitelist `AI_CATALOG` + `is_valid(provider, model)`. The single source of truth: validates PUT settings + feeds the `/ai/catalog` endpoint for the FE.
- **Cost guard**: `guild_ai_config.monthly_budget_usd` (Numeric) + `ai_usage.cost_usd` (Numeric, atomic increment alongside `tokens`, keyed by `period_key="YYYY-MM"`). `cost_this_period >= budget` → ValueError.
- **Key**: `guild_ai_config.api_key_enc` (LargeBinary, Fernet via `app/core/crypto.py`). NULL = not entered. The API never returns the key (only `has_key` + `key_hint`, the last 4 characters).
- **Config**: `AI_MAX_TOKENS` (default 400) is still used. `AI_MODEL` is only a reference default. `ANTHROPIC_API_KEY` is **deprecated** (no fallback). `TOKEN_ENCRYPTION_KEY` is required.
- **Tables**: `guild_ai_config` (enabled, provider, model, api_key_enc, monthly_budget_usd, persona), `ai_usage` (tokens + cost_usd/month). Migration v1 `d0e1f2a3b4c5`, v2 BYO-key `b4c5d6e7f8a9`.
- **Tests**: use `FakeAIProvider` → no network calls, deterministic; `LiteLLMProvider` tested by mocking `sys.modules["litellm"]`.

REST: GET/PUT `/guilds/{id}/ai/settings` (includes `has_key`/`key_hint`/`tokens_used_this_month`/`cost_used_this_month`), GET `/ai/catalog` (no guild_id needed), gated by `require_managed_guild` (catalog exempt from the gate + exempt from X-Client-ID).

---

## 5. Adding a new AI feature (template)

1. Write `XxxService(gateway: AIGateway)` with its own system prompt → call `gateway.complete(...)`.
2. The cog builds the gateway: `AIGateway(guild_repo, AIConfigRepository, AIUsageRepository, get_ai_provider())`.
3. Test with `FakeAIProvider`.

→ Summarizer / Q&A / Personality all follow this template.

---

## 6. Accepted limits (v2)

- **BYO-key per-guild** (servers pay their own way); provider/model from a **static catalog** (adding a new model = editing `catalog.py`); the USD budget is a **soft** fence (the last request may overshoot a bit because cost is known only after the call); cost is based on LiteLLM's pricing table (unknown model → cost 0 + log); an invalid/expired key → LiteLLM raises, no cost recorded. Cooldown + budget guard against burning money; content is LLM-generated so the system prompt forbids heavy insults but isn't absolute.
- **Non-goals for v2:** a dedicated LiteLLM Proxy, streaming, load-balancing across multiple keys, conversation history.
