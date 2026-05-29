# Leveling — End-to-end Workflow

> Companion to [`discord-architecture.md`](./discord-architecture.md). That document explains the *whole* app. This one zooms into the **leveling feature** (Phase 3.1): XP awarding, levels, role rewards, leaderboards and rank cards.
>
> **New to this codebase?** Read sections 1–3 in order — they build the mental model. Sections 4 onward are reference: dip in as needed. After reading you should be able to point at any line of leveling code and know where it sits in the flow.

---

## 1. What this feature does

A MEE6-style XP system, **per guild, off by default**. Admins turn it on from the dashboard. Once on:

- Every "real" chat message gives its author a random amount of XP (`xp_min..xp_max`), limited by a per-user cooldown and anti-spam filters.
- Gaining XP can push the member to a new **level**, which may:
  - post a level-up notification (to a channel, via DM, or off), and
  - add or replace the member's **level role rewards** (a role you get for hitting a level).
- Members run `/rank` to see a PNG rank card, or `/leaderboard` for the top earners. Admins can do the same things — plus edit settings — over REST from the dashboard.
- **(Opt-in) XP decay:** when enabled, a member who stops chatting for longer than a configurable threshold loses a configurable percentage of XP each period — eroding *only* the progress within their current level, so a level and its reward roles never get taken away. See [Flow E](#flow-e--inactivity-xp-decay-background-sweep).

Everything is scoped to one guild: two servers running this bot keep their XP, settings, rewards and themes completely separate.

---

## 2. Key concepts (read this first)

The flows below lean on a handful of patterns. Five minutes here saves confusion later.

| Term | What it means in this codebase |
|---|---|
| **`LevelingService` (the facade)** | The **single front door** to the whole feature. Every caller — the bot listener, slash commands, REST endpoints — talks *only* to this class. It delegates the real work to small **sub-services**. Internals can be rewired without touching callers. |
| **Sub-service** | A small, focused class the facade owns and composes: `XpAwarder`, `LevelRoleSync`, `LevelUpNotifier`, `LeaderboardService`, plus the `RankCardRenderer`. **Sub-services never call each other** — only the facade coordinates them. |
| **Unit of Work (UoW) / commit boundary** | One incoming request or gateway event = **one database transaction**. Repositories *never* commit; the commit happens once at the edge. If anything throws along the way, the whole transaction rolls back — no half-applied state. |
| **`flush` vs `commit`** | `flush()` pushes pending SQL inside the open transaction (so you can read back an auto-generated primary key) but doesn't make it permanent. `commit()` makes it permanent. **Repos flush; the boundary commits.** |
| **Config cache** | `LevelingConfigCache` — an in-memory dict (45-second TTL) holding each guild's `guild_leveling_config` row, keyed by Discord guild ID. Lets the hot path (every chat message) answer "is leveling on here?" **without a DB round trip**. |
| **Snowflake** | A Discord ID — a large 64-bit integer. Sent over JSON as a **string** (`"123..."`) because JSON numbers lose precision past 2⁵³. Handlers convert string → int before saving. |

Where the commit boundary actually lives:

- **HTTP requests** → `get_db` (in `app/db/session.py`) yields the session, then commits on success / rolls back on exception.
- **Bot events** (`on_message`, slash mutations, …) → `session_scope()`, an async context manager that does the same.
- **Read-only bot paths** → a plain session, no commit needed.

---

## 3. The big picture

Two entry surfaces — the Discord gateway and the dashboard's HTTP API — funnel into the **same** `LevelingService`, which talks to repositories, which talk to Postgres. The config cache sits to the side of the bot path as a fast-answer shortcut.

```
   Discord gateway                          Dashboard (browser)
        │                                          │
   on_message / slash command               HTTP REST call
        │                                          │
        ▼                                          ▼
 ┌─────────────────────┐                ┌─────────────────────┐
 │  Bot side           │                │  API side           │
 │  XpListenerCog      │                │  leveling.py        │
 │  LevelingCog        │                │  (api/v1/endpoints) │
 │  (bot/listeners,    │                │                     │
 │   bot/cogs)         │                │                     │
 └──────────┬──────────┘                └──────────┬──────────┘
            │                                       │
            │      both build the same service via DI
            └───────────────────┬───────────────────┘
                                 ▼
            ┌────────────────────────────────────────┐
            │            LevelingService              │
            │     the facade over everything below    │
            │                                         │
            │   XpAwarder         LevelRoleSync       │
            │   LevelUpNotifier   LeaderboardService  │
            │   RankCardRenderer                      │
            │   xp_calculator     content_filter      │
            └───────────────────┬─────────────────────┘
                                 ▼
                  ┌──────────────────────────┐
                  │       Repositories       │   one per table,
                  │   flush only — no commit │   commit happens
                  └─────────────┬────────────┘   at the boundary
                                ▼
                       ┌─────────────────┐
                       │    PostgreSQL   │
                       └─────────────────┘

   LevelingConfigCache (in-memory, 45 s TTL)
   sits beside the bot side: answers "is leveling on for this guild?"
   straight from memory so most chat messages never touch Postgres.
   → app/bot/cache/leveling_config_cache.py
```

The takeaway: **no matter where a call comes from, it ends up in `LevelingService`.** Callers never reach past the facade into a sub-service.

---

## 4. Data model

Five tables, all foreign-keyed to `guilds(id)` with `ON DELETE CASCADE`. See [`alembic/versions/20260527_140000_add_leveling_tables.py`](../alembic/versions/20260527_140000_add_leveling_tables.py).

| Table | Purpose | Key columns |
|---|---|---|
| `guild_leveling_config` | Per-guild on/off + tuning (cooldown, XP range, filters, ignored channels/roles, notification mode, level-role mode, **XP-decay toggle + percent + inactivity days**) | `guild_id` (PK) |
| `user_xp` | Cumulative XP per (guild, user) + last award time + **last decay time** | `(guild_id, user_id)` unique; `(guild_id, total_xp)` index for the leaderboard |
| `level_role_reward` | Level → Discord role mapping | `(guild_id, level)` unique |
| `guild_rank_card_theme` | Guild-default rank card palette | `guild_id` (PK) |
| `user_rank_card_theme` | Per-user theme override (Phase 3.1.5 placeholder) | `(guild_id, user_id)` unique |

**Enums** — three native Postgres enum types live in [`app/core/enums.py`](../app/core/enums.py) and back the columns below:

| Enum | Values | Column |
|---|---|---|
| `LevelRoleMode` | `stacking`, `replacing` | `guild_leveling_config.level_role_mode` |
| `NotificationMode` | `channel`, `dm`, `off` | `guild_leveling_config.notification_mode` |
| `BgType` | `solid`, `gradient` | `guild_rank_card_theme.bg_type`, `user_rank_card_theme.bg_type` |

**XP-decay columns** (added by [`alembic/versions/20260529_120000_add_xp_decay.py`](../alembic/versions/20260529_120000_add_xp_decay.py)):

| Column | Table | Meaning |
|---|---|---|
| `xp_decay_enabled` | `guild_leveling_config` | Decay on/off, independent of the master `enabled` toggle. |
| `xp_decay_percent` | `guild_leveling_config` | Percent removed per period (DB-checked 1–100). |
| `xp_decay_inactivity_days` | `guild_leveling_config` | Days of silence that make up one decay period (DB-checked ≥ 1). |
| `last_decay_at` | `user_xp` | When decay was last *settled* for this member. The sweep advances it so the next run doesn't re-charge already-decayed periods. |

---

## 5. End-to-end flows

Each flow is one vertical pipeline: read it top to bottom. The right column points at the file doing the work.

### Flow A — Member sends a chat message (the hot path)

This runs for *every* message, so it's optimised to bail out cheaply.

```
Discord gateway  (on_message event)
      │
      ▼
XpListenerCog.on_message                     app/bot/listeners/xp_listener.py
      │  opens session_scope  → starts the transaction (commit boundary)
      ▼
handle_message
      │  early-out if: author is a bot, it's a DM, or the cache says disabled
      ▼
LevelingConfigCache.get(guild_id)            in-memory, 45 s TTL
      │  cache hit → no DB round trip
      │  (guild that disabled leveling → cache returns None → stop here, zero DB cost)
      ▼
LevelingService.process_message              services/leveling/leveling_service.py
      │  walks gates cheapest-first; first failure returns None:
      │
      ├─ 1. is the guild registered with the bot?        GuildRepository.get_by_discord_id
      ├─ 2. is leveling enabled?                          GuildLevelingConfigRepository.get
      ├─ 3. is this channel in the ignored list?
      ├─ 4. does the member hold any ignored role?
      └─ 5. does the message content pass anti-spam?      content_filter.should_award
      ▼
XpAwarder.award                              services/leveling/xp_awarder.py
      │  acquire the per-(guild, user) lock  → serialises this one member's awards
      ├─ 6. cooldown gate: last_xp_at + cooldown_seconds vs now
      ├─ roll random XP in [xp_min, xp_max]
      ├─ compute new level                                xp_calculator.level_for_xp
      └─ write the row                                    UserXpRepository.set_xp (flush)
      ▼
returns AwardOutcome(amount, old_level, new_level, total_xp)
      │
      └─ leveled up? (new_level > old_level)
            ├─ LevelRoleSync.apply   → grant/strip the reward roles
            └─ LevelUpNotifier.send  → channel post or DM (best-effort)
      ▼
session_scope exits → COMMIT   (any exception above → ROLLBACK, XP un-written)
```

Worth internalising:

- The **only** DB read on the cheap-rejection path is the cache. Messages in guilds that disabled leveling cost **zero** DB hits (cache returns `None`).
- The level-up side effects (role sync, notification) run **inside the same transaction** as the XP write. If either fails, the XP write rolls back too — by design, since a clean retry beats half-applied state.
- The per-(guild, user) locks live in `XpAwarder._locks`, an LRU capped at `LOCK_CACHE_SIZE = 10_000`, so the dict can't grow without bound under load.

### Flow B — Slash command `/rank`

```
discord.py  /rank
      │
      ▼
LevelingCog.rank                             app/bot/cogs/leveling.py
      │  interaction.response.defer()  → tells Discord "working on it"
      ▼
_run_action(interaction, discord_io, do)
      │  async with session_scope() as session:   (commit boundary)
      ▼
LevelingService.build_rank_card_data   → RankCardData   (the only DB-row → dataclass mapper)
LevelingService.get_theme              → RankCardTheme   (guild default, else bot default)
      │
      ▼
RankCardRenderer.render_async                services/leveling/rank_card_renderer.py
      │  asyncio.to_thread(_render_sync, …)  → Pillow draws the PNG off the event loop
      ▼
interaction.followup.send(file=discord.File(png_bytes))
```

`/leaderboard` and `/level-rewards` follow the same `_run_action` shape but call `service.leaderboard(...)` / `reward_repo.list_by_guild(...)` and render an `Embed` instead of a PNG.

### Flow C — Admin updates settings over REST

```
PUT /api/v1/guilds/{id}/leveling/settings    app/api/v1/endpoints/leveling.py
      │
      ▼
get_db                                       app/db/session.py  (commit boundary)
      │  yields the session
      ▼
require_managed_guild                        auth + "is the bot actually in this guild?"
      │
      ▼
update_settings handler
      │  payload.model_dump() → convert snowflake strings to ints
      │
      ├─ GuildLevelingConfigRepository.upsert        (flush only)
      └─ invalidate the cache for this guild.discord_id
              reaches app.state.bot.leveling_config_cache.invalidate(...)
              so the next chat message picks up the new config immediately,
              instead of waiting out the 45 s TTL.
      ▼
return the updated settings
      ▼
get_db wraps up → COMMIT   (any exception → ROLLBACK)
```

Two invariants here:

1. **Cache invalidation happens before the response is sent.** If the request fails mid-flight, `get_db` rolls back and the cache key was merely cleared — the next message repopulates it from the (unchanged) DB row. No drift between cache and DB.
2. **Snowflakes arrive as strings** (`"1234"`) because JSON numbers lose precision past 2⁵³. The handler converts them to ints before persisting.

### Flow D — Admin resets a member

```
DELETE /api/v1/guilds/{id}/leveling/members/{user_id}
      │
      ▼
reset_member handler                         app/api/v1/endpoints/leveling.py
      │
      ▼
LevelingService.reset_member
      ├─ GuildRepository.get_by_discord_id
      ├─ UserXpRepository.delete                       (flush)
      └─ LevelRoleSync.apply(new_level=0)              strips every managed role
      ▼
service.get_rank  → a zeroed RankInfo
      ▼
return the member payload
      ▼
get_db → COMMIT
```

The `apply(new_level=0)` call is what strips the reward roles even when the member is offline — next time they appear in Discord they no longer hold rewards they haven't earned.

`PATCH …/members/{user_id}` works the same way but calls `set_member_xp` instead: it writes the new total, then runs role sync against the newly computed level.

### Flow E — Inactivity XP decay (background sweep)

Unlike A–D, this flow has **no caller** — it's a timer. `XpDecayCog` runs a `discord.py` `tasks.loop` once every 24 h. It's the only background loop in the bot, and unlike the chat/REST paths it touches the database **only**: no Discord calls, no notifications, no role changes (by design — decay can't change a level, so there's nothing to sync).

```
XpDecayCog.decay_sweep  (tasks.loop, every 24 h)        app/bot/cogs/xp_decay.py
      │  before_loop: await bot.wait_until_ready()
      │  now = datetime.now(UTC)        ← captured once, used for the whole sweep
      ▼
sweep_inactive_xp(now)                                  app/services/leveling/xp_decay.py
      │  loops batches until drained; EACH batch is its own session_scope (1 commit/batch)
      ▼
   per batch ──▶ XpDecaySweeper.decay_page(now, after_id, limit)
      │  fetch a page of candidates (id-cursor)          UserXpRepository.fetch_decay_page
      │    WHERE leveling enabled AND xp_decay_enabled AND total_xp > 0, ORDER BY id
      │
      │  for each (row, percent, days):
      │    anchor   = max(last_xp_at, last_decay_at)  (fallback created_at)
      │    periods  = full inactivity periods between anchor and now
      │    if periods < 1: skip (not idle long enough yet)
      │    floor    = total_xp_for_level(level_for_xp(total_xp))   ← current level's floor
      │    new_xp   = apply_decay(total_xp, floor, percent, periods)   ← compounded, clamped
      │    row.last_decay_at = anchor + periods·days     ← advance so we don't re-charge
      │    row.total_xp = new_xp (flush)
      ▼
   batch commits; loop advances the id-cursor until a short page ends the sweep
```

Why it's shaped this way:

- **Id-cursor pagination, not time-window paging.** Decay *mutates* the rows it visits, so a "fetch everything due" filter would keep re-finding them. Ordering by `id` and carrying `after_id` forward guarantees one clean pass that terminates.
- **One transaction per batch.** A single transaction over a huge `user_xp` table would lock/bloat; batching keeps each unit small and lets a mid-sweep failure leave already-processed batches committed.
- **Floor = current level threshold.** `apply_decay` clamps the result to `total_xp_for_level(level_for_xp(total_xp))`, so XP can dip within the level but never below it. Level is therefore invariant — which is exactly why this flow never calls `LevelRoleSync` or `LevelUpNotifier`.
- **`last_decay_at` is the bookkeeping anchor.** Advancing it by `periods·days` (not to `now`) preserves the sub-period remainder, so decay stays on a steady cadence across daily sweeps. A member who chats resets the clock naturally, because `last_xp_at` then becomes the later anchor.

---

## 6. The sub-services

All under [`app/services/leveling/`](../app/services/leveling/). Each module is deliberately small and depends only on the layers below it.

| Module | What it owns | Why it's its own file |
|---|---|---|
| `leveling_service.py` | The `LevelingService` **facade** — the only public entry point. Composes the rest. | A stable surface for HTTP, slash commands and the listener; internals can churn behind it. |
| `xp_calculator.py` | Pure XP↔level math (the MEE6 formula). | No I/O, fully testable, safe to import anywhere (no circular-import risk). |
| `xp_awarder.py` | Cooldown gate + random XP roll + per-user lock + persistence. | One concurrency-aware place to reason about XP races. |
| `content_filter.py` | "Should this message earn XP?" — min length, emoji-only, link-only. | Stateless, message-shape only; tests pass plain strings, no `discord.Message`. |
| `level_role_sync.py` | Diff the member's current roles against the target roles for the new level. | Same algorithm for stacking and replacing; orphan-cleanup logic kept in one spot. |
| `notification.py` | Channel post / DM / off — the level-up announcement. | Discord-side errors are swallowed here so the persistence path stays clean. |
| `leaderboard.py` | Paginated, level-decorated leaderboard view. | Lets HTTP and the `/leaderboard` cog share one shape. |
| `rank_card_renderer.py` | Pillow PNG draw, offloaded to a worker thread. | A CPU-bound draw must never block the gateway / FastAPI loop. |

Two facts that explain a lot of the design:

1. **Sub-services don't know about each other.** `XpAwarder` doesn't call `LevelRoleSync`; the facade does. That's why each level-up triggers exactly one role sync, even though both run inside `process_message`.
2. **The renderer is decoupled from the data shape.** `LevelingService.build_rank_card_data` is the *only* place that maps DB rows → `RankCardData`. The renderer takes plain dataclasses and returns bytes, so it's trivially swappable and testable.

**One deliberate exception — `xp_decay.py`.** The decay sweep ([Flow E](#flow-e--inactivity-xp-decay-background-sweep)) lives under `app/services/leveling/` too, but it is **not** a `LevelingService` sub-service: the facade is per-guild (its methods take a `guild_discord_id`), while the sweep is global — it scans every guild's rows in one pass. So `XpDecaySweeper` / `sweep_inactive_xp` are standalone and reached straight from `XpDecayCog`, not through the facade. The pure decay math still lives in `xp_calculator.py` (`apply_decay`), keeping the "all XP math in one pure module" rule intact.

---

## 7. Cross-cutting concerns

### Concurrency

- Each `(guild_id, user_id)` gets an `asyncio.Lock` in `XpAwarder._locks` — an `OrderedDict` used as an LRU, capped at 10 000 entries. A new key evicts the least-recently-used one; touching an existing key bumps it to most-recently-used, so active chatters don't get evicted under load.
- **Scaling to multiple processes:** swap `_lock_for` for `pg_advisory_xact_lock`. The lock is deliberately in-process for v1 to keep latency low.

### Caching

- `LevelingConfigCache` ([`app/bot/cache/leveling_config_cache.py`](../app/bot/cache/leveling_config_cache.py)) caches the entire `guild_leveling_config` row, keyed by Discord guild snowflake.
- TTL = 45 s — short enough that a misconfigured guild self-corrects quickly even with no dashboard activity.
- `PUT /settings` calls `cache.invalidate(...)` so admin changes take effect in milliseconds rather than waiting out the TTL.

### Unit of Work

- Repositories **never commit.** They `flush()` so a newly inserted row gets its auto-generated PK (needed before `refresh()`), but the transaction stays open.
- The commit happens at the request/event boundary:
  - **HTTP:** `get_db` yields the session, then `commit()` on success / `rollback()` on exception.
  - **Bot:** `session_scope()` (an `@asynccontextmanager`) does the same for `on_message`, `on_guild_join`, slash-command mutations, etc.
- **Read-only** cog paths use `AsyncSessionLocal()` directly — no commit needed for a read.

### Anti-spam (`content_filter.should_award`)

Three independent gates, each tunable per guild, run cheapest-first:

1. **Length** — strip the text, require `len >= min_message_length`.
2. **Emoji-only** — if `ignore_emoji_only`: strip Discord custom emoji + Unicode emoji ranges; if nothing remains, reject.
3. **Link-only** — if `ignore_link_only`: anchored regex `^https?://\S+/?$` matches the whole message, reject.

The bias is toward **false positives over false negatives** — better to miss a few legitimate messages than to reward emoji spam.

### Level math ([`xp_calculator.py`](../app/services/leveling/xp_calculator.py))

- `xp_to_next(L) = 5·L² + 50·L + 100` — the MEE6/Tatsu curve, so members migrating from those bots see familiar progression.
- `_thresholds` is precomputed at import time for levels `[0..MAX_LEVEL=500]`. A plain list — no locking, no I/O.
- `total_xp_for_level(L)` is `_thresholds[L]` — O(1).
- `level_for_xp(total)` binary-searches the threshold table — O(log MAX_LEVEL).

### XP decay ([`xp_decay.py`](../app/services/leveling/xp_decay.py) + [`bot/cogs/xp_decay.py`](../app/bot/cogs/xp_decay.py))

- **Pure math:** `apply_decay(total_xp, *, level_floor, percent, periods)` in `xp_calculator.py` returns `max(level_floor, round(total_xp · (1 − percent/100)^periods))`. Compounding on the remainder; clamped at the current level's floor. `periods ≤ 0` is a no-op. Pure → unit-tested with plain numbers.
- **Anchor & periods:** the sweeper measures inactivity from `max(last_xp_at, last_decay_at)` (falling back to `created_at`), and computes whole elapsed periods as `floor(elapsed_seconds / (days · 86400))`. Naive timestamps from SQLite are tagged UTC before subtraction.
- **Termination:** id-cursor pagination (`WHERE id > after_id ORDER BY id`) makes the mutate-while-scanning sweep a single finite pass; it stops when a page comes back shorter than the batch size.
- **Invariants:** level never decreases (floor clamp) ⇒ no role/notification side effects ⇒ no Discord calls. Decay is DB-only and runs off the chat hot path entirely.
- **Scheduling:** the only background loop in the bot — `XpDecayCog`'s `tasks.loop(hours=24)`, started in `setup_hook`, gated by `wait_until_ready()`.

### Role sync algorithm ([`level_role_sync.py`](../app/services/leveling/level_role_sync.py))

1. Load every reward row for the guild, ordered by level ascending.
2. Compute the **target** roles for `new_level`:
   - **replacing** → only the highest reward whose level ≤ new_level (or none).
   - **stacking** → every reward whose level ≤ new_level.
3. Read the member's current Discord roles via `BotDiscordClient.get_member_role_ids`.
4. `to_add = target − current`; `to_remove = (managed roles the member has) − target`.
5. Apply each add/remove:
   - **role deleted on Discord** (`DiscordNotFound` while adding) → drop the orphaned reward row (self-heal).
   - **missing permission** (`DiscordForbidden`) → log a warning and continue. One bad permission must not crash the whole level-up.

Step 4 is the key invariant: **the bot never strips a role it didn't grant.** Filtering by `managed_role_ids` keeps manually-assigned roles safe across a sync.

### Rank card render ([`rank_card_renderer.py`](../app/services/leveling/rank_card_renderer.py))

- `_render_sync` does the actual Pillow draw and returns PNG bytes.
- `RankCardRenderer.render_async` wraps it in `asyncio.to_thread` — the draw is CPU-bound, so running it inline would stall the gateway during high-XP traffic.
- Fonts cascade: bundled DejaVu in production containers → `ImageFont.load_default()` where it's absent, so tests need no fonts installed.

---

## 8. Operational notes

- **Cold start:** `Rolt9Bot.setup_hook` registers `LevelingCog`, `XpListenerCog`, and `XpDecayCog`. The config cache starts empty; the first message per guild costs one DB round trip. The decay loop waits for `wait_until_ready()` and then runs immediately, then every 24 h. No bootstrap step needed.
- **Failure modes:**
  - *DB down* → `process_message` raises, `session_scope` rolls back, no XP awarded. The cache TTL keeps a brief outage from poisoning config.
  - *Discord 403 on `add_role`* → swallowed with a warning. XP was still awarded; the member just won't get the role until permissions are fixed.
  - *Bundled font missing* → falls back to the PIL default. `/rank` still returns a PNG (just uglier).
  - *Decay sweep errors mid-run* → the failing batch's transaction rolls back; batches already committed stand. The next daily run resumes from `last_decay_at`, so nothing is double-charged.
- **Migrations:** `alembic upgrade head` creates 3 native enum types + 5 tables, then (a later revision) adds the 3 decay config columns + `user_xp.last_decay_at`. Downgrade drops them in reverse order, enums last.
- **Tests:** 88+ tests cover the slice — unit (`tests/unit/test_leveling_*.py`) for sub-services, integration (`tests/integration/test_leveling_*_routes.py`) for endpoints. `tests/conftest.py` swaps `get_db` for an in-memory SQLite engine with `expire_on_commit=False`.

---

## 9. Quick reference

### REST endpoints

All under `/api/v1/guilds/{guild_id}/leveling/…`; require dashboard auth + `manage_guild` permission on that guild.

| Method | Path | Handler |
|---|---|---|
| `GET` | `/settings` | `get_settings` (includes the `xp_decay_*` fields) |
| `PUT` | `/settings` | `update_settings` (invalidates cache; validates `xp_decay_percent` 1–100, `xp_decay_inactivity_days` ≥ 1) |
| `GET` | `/leaderboard?page=&page_size=` | `get_leaderboard` |
| `GET` | `/members/{user_id}` | `get_member` |
| `PATCH` | `/members/{user_id}` | `update_member` (admin override + role sync) |
| `DELETE` | `/members/{user_id}` | `reset_member` (zero + strip roles) |
| `GET` | `/rewards` | `list_rewards` |
| `POST` | `/rewards` | `create_reward` |
| `DELETE` | `/rewards/{level}` | `delete_reward` |
| `GET` | `/rank-card-theme` | `get_theme` |
| `PUT` | `/rank-card-theme` | `update_theme` |

### Slash commands ([`app/bot/cogs/leveling.py`](../app/bot/cogs/leveling.py))

| Command | Behaviour |
|---|---|
| `/rank [member]` | Renders a PNG rank card. Defaults to the caller. |
| `/leaderboard [page]` | Posts a per-page Embed of top XP earners. |
| `/level-rewards` | Lists the guild's level → role mapping. |

---

## 10. Where to start reading the code

- **Trace an XP award:** `xp_listener.py` → `handle_message` → `LevelingService.process_message` → `XpAwarder.award`.
- **Trace a slash command:** `cogs/leveling.py::LevelingCog.rank` → `_run_action` → `LevelingService.build_rank_card_data` → `RankCardRenderer.render_async`.
- **Trace a REST call:** `api/v1/endpoints/leveling.py` → `LevelingService` → repos.
- **Trace XP decay:** `bot/cogs/xp_decay.py::XpDecayCog.decay_sweep` → `services/leveling/xp_decay.py::sweep_inactive_xp` → `XpDecaySweeper.decay_page` → `apply_decay` (`xp_calculator.py`).
- **Add a new sub-service:** copy any file under `services/leveling/`, then wire it into `LevelingService.__init__`. Sub-services never import each other, so adding one doesn't ripple.
