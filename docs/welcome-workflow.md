# Welcome — Guide & Workflow

**Welcome** messages for new members (`on_member_join`) and **goodbye** messages when they leave
(`on_member_remove`). Supports static templates (placeholders) + an **AI**-generated greeting (optional).

---

## 1. Overview

- A member **joins** → the bot renders a template (or asks the AI) → posts it to the **configured channel**.
- A member **leaves** → the bot posts a goodbye template (static, no AI) to the same channel.
- Everything is off by default; the admin enables it + picks a channel on the dashboard.

---

## 2. For admins — Dashboard → server → Welcome

| Field | Meaning | Default |
|---|---|---|
| **Enable welcome** | Turn the welcome message on/off when someone joins | off |
| **Channel** | The channel that posts both welcome and goodbye messages | — (required when enabled) |
| **Welcome template** | The welcome message template (uses the placeholders below) | "Welcome {user} to {server}! 🎉 You are member number {count}." |
| **AI-generated welcome** | Have Claude write the greeting (still @mentions the member); error/quota exhausted → auto-falls back to the template | off |
| **Enable leave message** | Turn the goodbye message on/off when someone leaves | off |
| **Leave template** | The goodbye message template (static, no AI) | "{user} has left **{server}**. 👋" |

**Placeholders** (substituted with `str.replace`, not `format` — so a stray `{}` in the text won't cause errors):

| Placeholder | Replaced with |
|---|---|
| `{user}` | Member mention/name |
| `{server}` | Server name |
| `{count}` | Current member count |

**Operation:**
- You must enable the **privileged intent `Server Members`** in the Discord Developer Portal (the bot already declares `intents.members = True`).
- AI welcome shares the same `AIGateway` (see [ai-workflow](ai-workflow.md)) — needs `ANTHROPIC_API_KEY` + remaining monthly quota; if missing → auto-falls back to the template.

---

## 3. Internals (for devs)

```
on_member_join → WelcomeCog → WelcomeService.build_welcome(...)
   ├─ config.enabled? has channel_id? (no → return None, skip)
   ├─ render_template(welcome_template, user/server/count)
   ├─ if ai_welcome: gateway.complete(WELCOME_SYSTEM, prompt) → prefix mention
   │     └─ ValueError (off/missing key/quota exhausted) → fall back to text template
   └─ return (channel_id, text) → cog posts via discord_io (swallows DiscordError)

on_member_remove → WelcomeCog → WelcomeService.build_leave(...)  # static, no AI
```

- **`render_template`** (`services/welcome/template.py`): pure str.replace, no I/O — easy to test.
- **`WelcomeService`** (`services/welcome/welcome_service.py`): depends on `guild_repo`, `config_repo`, `gateway`. `build_welcome`/`build_leave` return `tuple[int, str] | None` (None = don't post). An AI error → swallowed, falls back to the template (never breaks the join event).
- **`WelcomeCog`** (`bot/cogs/welcome.py`): a thin listener; `_post` swallows `DiscordError` so a wrong channel/missing permission doesn't break the event.
- **Config table**: `guild_welcome_config` (guild_id PK, enabled, channel_id BigInteger nullable, welcome_template, ai_welcome, leave_enabled, leave_template). Repo follows the no-404 pattern: `get`/`get_or_create`/`upsert`. Migration `a3b4c5d6e7f8`.
- **Tests**: `FakeAIProvider` for the AI branch → no network calls, deterministic.

REST: GET/PUT `/guilds/{id}/welcome/settings`, gated by `require_managed_guild`. `channel_id` is a **string snowflake** on the wire, coerced int↔str at the endpoint boundary.

---

## 4. Accepted limits (v1)

- One shared channel for both join and leave (not yet split); leave is always static (no AI) to save tokens; no welcome image/banner (text-only); fixed placeholders (`{user}/{server}/{count}`).
