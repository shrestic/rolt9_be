# Server Currency — End-to-end Workflow

> Companion to [`discord-architecture.md`](./discord-architecture.md) and [`leveling-workflow.md`](./leveling-workflow.md). This one zooms into the **server-currency feature** (Phase 3.2, the economic substrate for Quests / Mini-games / Server Pet): wallets, earning, daily rewards, transfers, leaderboards, and admin controls.
>
> **New to this codebase?** Read sections 1–3 in order — they build the mental model (the one idea that matters is **atomic balance updates**). Sections 4 onward are reference.

---

## 1. What this feature does

A per-guild virtual economy, **off by default**, opt-in per server (exactly like leveling — two servers keep entirely separate economies). When an admin turns it on:

- **Passive earn:** every "real" chat message that earns XP also grants a small random amount of currency (it *piggybacks* on the XP award, so it reuses all the anti-spam/cooldown gating for free).
- **`/daily`:** a fixed reward claimable once per 24 hours.
- **`/pay`:** transfer currency to another member (if the admin allows it).
- **`/balance` / `/baltop`:** check a wallet / see the richest members.
- **`/eco give|take|reset`:** admin balance controls (needs *Manage Server*).
- The currency's **name and emoji are per-guild** (e.g. "xu" 🪙), set from the dashboard.

There is intentionally **no "sink"** yet (no shop, no gambling) — those arrive as later Phase 3.2 sub-projects. v1 is the wallet + the faucets.

---

## 2. Key concepts (read this first)

| Term | What it means here |
|---|---|
| **Atomic guarded UPDATE** | The heart of the feature. Every balance change is **one** SQL statement like `UPDATE … SET balance = balance + :delta WHERE … AND balance + :delta >= 0`. The check and the write happen together, so balances can never go negative and two concurrent spends can't both succeed. **No application-level lock is needed** — the database arbitrates. |
| **Piggyback earn** | Currency isn't a second message listener. The XP listener, *after* a message successfully earns XP, calls `CurrencyService.grant_message_reward`. So passive earn inherits the leveling anti-spam + per-user cooldown and only runs when **both** leveling and currency are enabled. |
| **`CurrencyService` (facade)** | The single entry point for **bot-facing** money flows (grant / daily / pay / admin / leaderboard). Resolves the Discord guild snowflake → internal UUID, enforces the on/off toggle and the amount cap, and delegates to the repos. |
| **Amount cap (`MAX_AMOUNT = 1_000_000`)** | Every `/pay` and `/eco` amount is bounded `1..1_000_000`. Blocks overflow, fat-finger typos, and runaway inflation. Config values are capped too (earn ≤ 10k, daily ≤ 1M). |
| **`BigInteger` balance** | 64-bit, so a long-lived/active economy or admin grants can't overflow. |
| **Unit of Work (UoW)** | Same as the rest of the app: repos only `flush()`; the commit happens once at the boundary — `get_db` for HTTP, `session_scope()` for bot events. A failed `/pay` rolls the whole transaction back. |
| **Error convention** | `CurrencyService` raises `LookupError` when the guild isn't registered with the bot, and `ValueError` for user-facing rejections (disabled, bad amount, insufficient funds). The one silent path is `grant_message_reward`, which returns `None` when off (it runs on the chat hot path). |

---

## 3. The big picture

Two entry surfaces feed the same wallet table. The **bot side** (slash commands + the passive-earn hook) goes through `CurrencyService`; the **dashboard REST side** talks to the repositories directly (there's no cross-guild business logic for settings/leaderboard/member admin, so a facade would add nothing).

```
   Discord gateway                              Dashboard (browser)
        │                                              │
   ┌────┴─────────────────────────┐              HTTP REST call
   │                              │                    │
 slash cmd                  on_message                 ▼
 /balance /daily /pay        (passive earn)   ┌─────────────────────┐
 /baltop /eco                     │           │  API side           │
        │                         │           │  currency.py        │
        ▼                         ▼           │  (api/v1/endpoints) │
 ┌──────────────┐     ┌───────────────────┐  └──────────┬──────────┘
 │ CurrencyCog  │     │ XpListenerCog      │             │
 │ (bot/cogs)   │     │  → after XP award  │   settings / leaderboard /
 └──────┬───────┘     └─────────┬──────────┘   member admin go straight
        │                       │              to the repositories
        ▼                       ▼                        │
   ┌─────────────────────────────────┐                   │
   │         CurrencyService          │                  │
   │  grant / daily / pay / admin     │                  │
   │  (bot-facing facade)             │                  │
   └────────────────┬─────────────────┘                  │
                    ▼                                     ▼
        ┌──────────────────────────────────────────────────────┐
        │  Repositories                                          │
        │  WalletRepository — ATOMIC guarded UPDATEs             │
        │  CurrencyConfigRepository — settings get/upsert        │
        │  flush only — commit at the boundary                   │
        └───────────────────────────┬────────────────────────────┘
                                     ▼
                            ┌─────────────────┐
                            │    PostgreSQL   │
                            └─────────────────┘
```

Takeaway: **all balance mutations funnel through `WalletRepository`'s atomic UPDATEs**, whether they came from a slash command, the passive hook, or an admin REST call. That single chokepoint is what makes the whole feature race-safe.

---

## 4. Data model

Two tables, both FK to `guilds(id)` with `ON DELETE CASCADE`. Added by [`alembic/versions/20260529_140000_add_currency.py`](../alembic/versions/20260529_140000_add_currency.py).

| Table | Purpose | Key columns / notes |
|---|---|---|
| `guild_currency_config` | Per-guild on/off + tuning | `guild_id` (PK). `enabled`, `currency_name` (≤32), `currency_emoji` (≤32), `earn_min`/`earn_max`, `daily_amount`, `allow_pay`. Check constraints: amounts ≥ 0, `earn_min ≤ earn_max`. |
| `user_wallet` | One balance per (guild, member) | `(guild_id, user_id)` unique; index `(guild_id, balance)` for `/baltop`. `balance` is **BigInteger**, check `balance >= 0`. `last_daily_at` (nullable) drives the 24h cooldown. |

Wallets are created **lazily** (`WalletRepository.get_or_create`) the first time a member earns/receives — "no row" just means balance 0.

**Defaults:** `enabled=false`, `currency_name="coins"`, `currency_emoji="🪙"`, `earn_min=1`, `earn_max=3`, `daily_amount=100`, `allow_pay=true`.

---

## 5. End-to-end flows

Read each top to bottom; the right column points at the file doing the work.

### Flow A — Passive earn (piggyback on XP)

```
Discord gateway  (on_message)
      ▼
XpListenerCog.on_message                          app/bot/listeners/xp_listener.py
      │  builds LevelingService + CurrencyService on one session_scope
      ▼
handle_message
      ├─ outcome = LevelingService.process_message(...)   → AwardOutcome | None
      │     (None ⇒ blocked by anti-spam / cooldown / disabled)
      │
      └─ if outcome is not None and currency_factory:
             CurrencyService.grant_message_reward(guild_discord_id, user_id)
                ├─ guild registered? currency enabled?  (else silent no-op)
                ├─ amount = random.randint(earn_min, earn_max)
                └─ WalletRepository.add_balance(+amount)   ← atomic UPDATE
      ▼
session_scope exits → COMMIT
```

The crucial line is `if outcome is not None`: currency is granted **only** when XP was actually awarded, so the message already passed min-length / emoji-only / link-only / cooldown. No duplicate gating.

### Flow B — `/daily` (with streak)

```
/daily  →  CurrencyCog.daily                       app/bot/cogs/currency.py
      │  defer(ephemeral) → session_scope → CurrencyService.claim_daily
      ▼
CurrencyService.claim_daily(now=now)               app/services/currency/currency_service.py
      ├─ currency enabled? (else ValueError)
      ├─ read wallet (last_daily_at, current_streak, longest_streak)
      ├─ streak math (app/services/currency/streak.py):
      │     new_streak = next_streak(last_daily_at, now, current)   ← ≤48h ago → +1, else 1
      │     s_bonus    = min(new_streak * per_day, cap)
      │     m_bonus    = MILESTONES.get(new_streak, 0)              ← {7,30,100,365}
      │     (streak disabled → new_streak=0, no bonuses; chain dropped)
      ├─ total = daily_amount + s_bonus + m_bonus
      └─ WalletRepository.try_claim_daily(total, now, cutoff, new_streak, new_longest)  ← atomic
              UPDATE … SET balance += total, last_daily_at = now,
                          current_streak = new_streak, longest_streak = new_longest
               WHERE … AND (last_daily_at IS NULL OR last_daily_at <= cutoff)
      ▼
   claimed?  → "+130 🪙 … 🔥 Chuỗi 3 ngày … 🎉 Mốc 7 ngày! +200"
   on cooldown (0 rows) → "wait Xh Ym"  (retry_after computed from last_daily_at)
```

The cooldown test lives **inside the UPDATE's WHERE**, so two `/daily` fired at the same instant can't both pass — only one matches. The streak counters are computed in Python from the pre-claim read, but that's still race-safe: only the single UPDATE whose WHERE still matches actually writes, so a losing concurrent claim never persists a stale/duplicate streak. The `/daily` reward window also keeps the chain alive — claim again within **48h** of the previous claim to continue (24h cooldown means the live window is effectively `[24h, 48h]`); miss a full day and the chain restarts at 1.

**`/streak [member]`** → `CurrencyService.get_streak` → reads `current_streak` / `longest_streak` off the wallet (never raises; unknown guild or no wallet reports a zero, disabled streak). Shows current chain, all-time record, and days to the next milestone.

> **Streak disabled** (`streak_enabled=false`): `/daily` grants base only and the chain is dropped to 0 (record `longest_streak` is preserved). Re-enabling later therefore restarts the chain from 1 — it does not resume the old count.

### Flow C — `/pay` (transfer)

```
/pay @bob 200  →  CurrencyCog.pay
      │  rejects paying a bot before hitting the service
      ▼
CurrencyService.pay(sender, receiver, amount)
      ├─ enabled? allow_pay? amount in 1..1_000_000? sender ≠ receiver?  (else ValueError)
      ├─ add_balance(sender,  -amount)   ← atomic guard; 0 rows ⇒ insufficient → raise
      └─ add_balance(receiver, +amount)
      ▼
session_scope → COMMIT   (both updates in one transaction; any failure rolls back both)
```

Because the debit is a guarded UPDATE and both legs share one transaction, money is never created, lost, or overdrawn — even under concurrent transfers.

### Flow D — `/balance`, `/baltop`

`/balance [member]` → `CurrencyService.get_balance` → `WalletRepository.get` (0 if no wallet).
`/baltop` → `CurrencyService.leaderboard` → `WalletRepository.leaderboard` (DESC balance, `user_id` tie-break, backed by the `(guild_id, balance)` index).

### Flow E — `/eco give|take|reset` (admin, in Discord)

Gated by `@app_commands.default_permissions(manage_guild=True)` on the `eco` group.
- `give`/`take` → `CurrencyService.admin_add(±amount)` (a take that exceeds the balance fails the guard ⇒ raises "can only take up to N", rather than silently clamping).
- `reset` → `CurrencyService.admin_set(0)`.

### Flow F — Dashboard REST

```
GET/PUT  /api/v1/guilds/{id}/currency/settings        app/api/v1/endpoints/currency.py
GET      /api/v1/guilds/{id}/currency/leaderboard
GET/PATCH/DELETE /api/v1/guilds/{id}/currency/members/{user_id}
      │  all gated by require_managed_guild (auth + manage_guild + bot-in-guild)
      ▼
settings → CurrencyConfigRepository (get_or_create / upsert)
leaderboard + members → WalletRepository directly  (set_balance for PATCH, 0 for DELETE)
      ▼
get_db → COMMIT
```

Settings round-trip mirrors leveling: `get_settings` uses `get_or_create` so a fresh guild sees defaults (never a 404); `update_settings` validates through the `CurrencySettings` Pydantic schema.

---

## 6. The components

| File | Responsibility |
|---|---|
| [`app/models/guild_currency_config.py`](../app/models/guild_currency_config.py) | Config table + check constraints. |
| [`app/models/user_wallet.py`](../app/models/user_wallet.py) | Wallet table (BigInteger balance, `last_daily_at`). |
| [`app/repositories/user_wallet.py`](../app/repositories/user_wallet.py) | **The atomic core.** `add_balance` (guarded ±), `try_claim_daily` (guarded + cooldown), `set_balance`, `leaderboard`, `rank_of`. |
| [`app/repositories/currency_config.py`](../app/repositories/currency_config.py) | `get` / `get_or_create` / `upsert` config. |
| [`app/services/currency/currency_service.py`](../app/services/currency/currency_service.py) | Bot-facing facade; guild resolution, toggle/cap enforcement, the two-step `pay`, daily retry math. `DailyResult` is its return DTO for `/daily`. |
| [`app/bot/cogs/currency.py`](../app/bot/cogs/currency.py) | Slash commands; thin (defer → session_scope → service → reply, mapping errors to a ❌ message). |
| [`app/bot/listeners/xp_listener.py`](../app/bot/listeners/xp_listener.py) | Passive-earn hook (the `currency_factory` call after a successful award). |
| [`app/api/v1/endpoints/currency.py`](../app/api/v1/endpoints/currency.py) | Dashboard REST. |
| [`app/schemas/currency.py`](../app/schemas/currency.py) | `CurrencySettings` + wallet DTOs, with the validation caps. |

---

## 7. Cross-cutting concerns

### Atomicity (the whole game)
Every mutation is a single guarded `UPDATE`:
- **Balance:** `... SET balance = balance + :delta WHERE ... AND balance + :delta >= 0` → `rowcount 0` means "would overdraw" (returns `False`); the check is inseparable from the write, so no read-modify-write race and **no app lock**.
- **Daily:** the same shape with the 24h cooldown predicate in the WHERE.
- **`/pay`:** debit + credit in one transaction; debit failure aborts both.

### Anti-abuse — what's covered vs. accepted (v1)
- **Covered for free** (via piggyback): emoji-only / link-only / too-short spam can't farm (no XP ⇒ no currency); per-user cooldown (switching channels doesn't bypass); bot authors filtered; edits/deletes after sending don't matter.
- **Covered by design:** balance can't go negative (guard + check constraint); `/daily` can't double-claim (atomic cooldown); `/pay` can't overdraw / self-pay / pay a bot / send ≤0 or > cap; amounts capped at 1M; BigInteger prevents overflow.
- **Accepted limits (no v1 fix):** alt-account farming + `/pay` laundering to a main account is a Discord-level problem (future mitigations: pay tax, per-day pay limit, account-age gate). Inflation is expected until sinks (shop / mini-games / pet) land — `/baltop` is decorative until then. Admins can inflate via `/eco` — that's trusted-by-design; the cap only stops typos.

### Locking down the `/eco` admin commands

`/eco give|take|reset` are the dangerous commands (they can mint or wipe balances). They are gated **in code** by `@app_commands.default_permissions(manage_guild=True)` on the `eco` group, so Discord hides the whole group from anyone who doesn't hold **Manage Server**. The server owner always sees it; so does any member whose role grants Manage Server (or Administrator). The public commands (`/balance`, `/daily`, `/pay`, `/baltop`) have no such gate.

To restrict `/eco` further **without any code change**, a server admin uses Discord's native per-command override — `default_permissions` is only the *default*, and a server-level override replaces it:

1. **Server Settings → Integrations → [rolt9 bot] → Manage.**
2. Pick the **`/eco`** command (overriding the parent applies to `give`/`take`/`reset`).
3. Under **Roles & Members**, disable `@everyone` and allow only a dedicated **"Economy Admin"** role. Optionally add a **Channels** restriction to a single channel.
4. Save. Only that role (plus the owner) can now run `/eco`.

Notes: editing these overrides requires Manage Server; the commands must already be synced (they are — `setup_hook` calls `tree.sync()`); this is **per-server**, configured by each guild's admins — the bot can't enforce it globally.

> If you ever want the *bot itself* to enforce a dedicated econ-admin role (rather than relying on each owner to set the Integrations override), that needs code: store an `eco_admin_role_id` on `guild_currency_config` and check it in the cog. Out of scope for v1.

### Dependency on leveling
Passive earn requires leveling **enabled** (it rides the XP award). `/daily`, `/pay`, and admin commands are independent of leveling. If a server wants currency without chat-earning, they simply leave passive earn effectively unused and rely on `/daily`.

### Unit of Work
Repos never commit. Bot flows commit at `session_scope` exit; REST at `get_db`. A `/pay` that throws mid-way rolls back both balance writes.

---

## 8. Operational notes

- **Migration:** `alembic upgrade head` creates the two tables (revision `c3d4e5f6a7b8`, after the xp-decay head `b2c3d4e5f6a7`). In docker: `docker compose exec api alembic upgrade head`. Tests don't need it — they build the schema from the models via `Base.metadata.create_all` on SQLite.
- **Slash command registration:** `CurrencyCog` is registered in `Rolt9Bot.setup_hook`, which also calls `tree.sync()`. On a uvicorn `--reload` restart the bot reconnects and re-syncs. **Global** command propagation in the Discord client can take a few minutes — restart the bot if commands don't appear.
- **Failure modes:**
  - *Currency table missing* (forgot the migration) → the passive hook and REST raise `UndefinedTableError`. Fix = run the migration.
  - *Currency disabled* → slash commands reply "not enabled"; passive earn is a silent no-op.
  - *Insufficient funds / cooldown* → friendly ❌ message; nothing is written.
- **Tests:** unit (`tests/unit/test_currency_*.py`) cover the atomic repo ops, the daily race, pay guards, and the service; integration (`tests/integration/test_currency_*_routes.py`) cover the REST surface. All run on in-memory SQLite.

---

## 9. Quick reference

### Slash commands ([`app/bot/cogs/currency.py`](../app/bot/cogs/currency.py))

| Command | Behaviour |
|---|---|
| `/balance [member]` | Show a wallet balance (defaults to caller). |
| `/daily` | Claim the daily reward (24h cooldown) + advance the streak. |
| `/streak [member]` | Show a daily-claim streak (current, record, next milestone). |
| `/pay <member> <amount>` | Transfer currency (if `allow_pay`). |
| `/baltop` | Top 10 richest members. |
| `/eco give <member> <amount>` | Admin: add currency (`Manage Server`). |
| `/eco take <member> <amount>` | Admin: remove currency. |
| `/eco reset <member>` | Admin: set balance to 0. |

### REST endpoints — under `/api/v1/guilds/{guild_id}/currency/…`, require dashboard auth + `manage_guild`

| Method | Path | Handler |
|---|---|---|
| `GET` | `/settings` | `get_settings` (defaults on first call) |
| `PUT` | `/settings` | `update_settings` (validates caps + `earn_min ≤ earn_max`) |
| `GET` | `/leaderboard?page=&page_size=` | `get_leaderboard` |
| `GET` | `/members/{user_id}` | `get_member` |
| `PATCH` | `/members/{user_id}` | `update_member` (set absolute balance) |
| `DELETE` | `/members/{user_id}` | `reset_member` (balance → 0) |

### Config fields (`guild_currency_config` / `CurrencySettings`)

| Field | Default | Bounds |
|---|---|---|
| `enabled` | `false` | — |
| `currency_name` | `coins` | 1–32 chars |
| `currency_emoji` | `🪙` | 1–32 chars |
| `earn_min` / `earn_max` | `1` / `3` | 0–10,000; `earn_min ≤ earn_max` |
| `daily_amount` | `100` | 0–1,000,000 |
| `allow_pay` | `true` | — |
| `streak_enabled` | `true` | — |
| `streak_bonus_per_day` | `10` | 0–10,000 (bonus = `min(streak × per_day, cap)`) |
| `streak_bonus_cap` | `500` | 0–1,000,000 |

Streak milestones are hardcoded (v1, not FE-configurable): `{7: 200, 30: 1000, 100: 5000, 365: 20000}` coins — see `app/services/currency/streak.py`.

---

## 10. Where to start reading the code

- **Trace passive earn:** `xp_listener.py::handle_message` → `CurrencyService.grant_message_reward` → `WalletRepository.add_balance`.
- **Trace `/daily`:** `cogs/currency.py::CurrencyCog.daily` → `CurrencyService.claim_daily` → `WalletRepository.try_claim_daily`.
- **Trace `/pay`:** `CurrencyCog.pay` → `CurrencyService.pay` → two `WalletRepository.add_balance` calls.
- **Trace a dashboard save:** `api/v1/endpoints/currency.py::update_settings` → `CurrencyConfigRepository.upsert`.
- **Understand the safety model:** read `WalletRepository.add_balance` and `try_claim_daily` first — the guarded UPDATE is the one idea everything else rests on.
