# Quests — Guide & Workflow

Daily/weekly quests that **admins create themselves**. Members make enough progress → type `/quests claim` to receive coins.

---

## 1. What this feature does

- Admins create quests via the dashboard: set an **objective** (earn coins / check-in), a **period** (daily/weekly), a **target**, and a **coin reward**.
- Members chat (passive coin earning) or `/daily` → quest progress increases automatically.
- Enough progress → `/quests claim` collects all coins at once.
- Progress **resets per period**: daily resets at 00:00 UTC, weekly resets Monday 00:00 UTC.

> **Dependency:** Quests require **Currency enabled** (objectives count coins/check-ins, rewards = coins). Enable Currency first.

---

## 2. For admins — creating quests (Dashboard)

Go to **Dashboard → server → Quests**. Each quest has:

| Field | Meaning |
|---|---|
| **Name** | Display name (e.g. "Daily grind") |
| **Description** | Description (optional) |
| **Period** | `daily` (resets each day) or `weekly` (resets each week) |
| **Objective** | `Earn coins` (accumulate coins received) or `Check-in` (count /daily claims) |
| **Target** | Progress required (1–100,000) |
| **Reward coins** | Coins rewarded on completion (0–1,000,000) |
| **Enabled** | Turn the quest on/off |

Create / edit / delete / toggle freely. Disabling a quest → it doesn't show to members and no longer tracks progress.

**Suggested quest set example:**
- `daily` · Earn coins · target 200 · reward 50 → "Earn 200 coins today".
- `daily` · Check-in · target 1 · reward 30 → "Check in today".
- `weekly` · Check-in · target 5 · reward 300 → "Check in 5 days this week".
- `weekly` · Earn coins · target 2000 · reward 500 → "Earn 2000 coins this week".

---

## 3. For members — Discord commands

| Command | What it does |
|---|---|
| `/quests list` | View quests + progress bars + status (in progress / ✅ ready / ☑️ claimed) |
| `/quests claim` | Claim **all** quests that have enough progress, reporting the total coins |

Progress increases automatically when: **chatting** (each coin-earning message → adds to "Earn coins" quests), **`/daily`** (adds the coins received + 1 check-in).

---

## 4. Internals (for devs)

```
Member chats → xp_listener → currency.grant_message_reward(amount)
                              └→ QuestService.record_event("earn_coins", amount)

/daily → CurrencyCog.daily → claim_daily
            └→ QuestService.record_event("earn_coins", res.amount)
            └→ QuestService.record_event("daily_claim", 1)

/quests claim → QuestService.claim (atomic try_claim per quest → WalletRepository.add_balance)
```

- **Period key**: daily = UTC date (`2026-05-30`), weekly = ISO week (`2026-W22`). Progress is stored by `period_key` → a new period gets a new row, auto-resetting to 0.
- **Atomic**: `increment` accumulates in SQL (no lost-update); `try_claim` is a guarded UPDATE (`progress>=target AND claimed=false`) → can't claim twice.
- **Decoupled**: QuestService reads through repos, rewards via `WalletRepository.add_balance` directly (does not call CurrencyService).
- **Tables**: `guild_quest` (definitions), `user_quest_progress` (progress per user/quest/period, unique `(quest_id,user_id,period_key)`).
- **Hot path**: recording earn_coins per coin-earning message = 1 SELECT (enabled earn quests, indexed) + UPDATE/quest. Accepted for v1.

REST CRUD: `GET/POST /guilds/{id}/quests`, `PATCH/DELETE /guilds/{id}/quests/{quest_id}` (gated by `require_managed_guild`). PATCH is a partial update (only the fields sent are changed).

---

## 5. Operation

- **After adding a migration while the stack is running:** `docker compose exec api alembic upgrade head` (uvicorn `--reload` does NOT run migrations). Quests migration: `f6a7b8c9d0e1`.
- **v1 limits (accepted):** editing the target while members are in progress → counts against the new target; old-period rows are not cleaned up; quests are useless if currency is off.
