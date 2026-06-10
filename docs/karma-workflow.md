# Karma — Guide & Workflow

Peer-rated reputation points. Members award karma to one another with `/karma give @user`.

---

## 1. What this feature does

- A member awards **+1 karma** to someone else via `/karma give @user` to recognize a contribution/help.
- **Add only** (no downvote) — keeps the vibe positive.
- **Per-pair 24h cooldown**: each person can only +1 the **same person** once per 24h (you can freely praise different people).
- Blocks self-praise + blocks praising bots.
- **Pure reputation** — karma doesn't convert to coins/badges; the value is reputation + the leaderboard.
- Standalone, no currency/leveling needed.

---

## 2. For admins — Dashboard → server → Karma

- **Enable karma**: turn on/off (default off).
- View the karma **leaderboard** (top members).

(There are no numbers to tune — karma is just +1/award, with a fixed 24h cooldown.)

---

## 3. For members — Discord commands

| Command | What it does |
|---|---|
| `/karma give <member>` | Award +1 karma. Blocks bots/self-praise → ❌. Already praised that person <24h ago → ❌ |
| `/karma view [member]` | View your/someone else's karma points + rank |
| `/karma top` | Leaderboard of the top 10 highest-karma people |

---

## 4. Internals (for devs)

```
/karma give @X → KarmaCog (blocks bot + self) → KarmaService.give
  ├─ config enabled? giver≠receiver?
  ├─ KarmaGrantRepository.try_grant(giver, receiver, now, now-24h)  ← atomic; failure → ValueError (NO point added)
  └─ KarmaRepository.add_point(receiver)  ← atomic points+1
```

- **Atomic**: `try_grant` is a guarded UPDATE (per-pair cooldown in the WHERE) → no bypass/no double-grant; `add_point` accumulates in SQL → no lost-update.
- **Safe ordering**: claim the cooldown FIRST, and on failure raise immediately → a blocked grant never adds a point.
- **Decoupled**: KarmaService only reads through repos, never calling another service.
- **Tables**: `guild_karma_config` (toggle), `user_karma` (points received, index `(guild_id,points)` for the leaderboard), `karma_grant` (per-pair giver→receiver cooldown ledger).
- **Leaderboard**: points DESC, tie-break user_id ASC; `rank_of` = number of people with more points + 1. user_id comes over the wire as a string (snowflake).

REST: GET/PUT `/guilds/{id}/karma/settings`, GET `/guilds/{id}/karma/leaderboard?page&page_size` (gated by `require_managed_guild`).

---

## 5. Operation

- **Adding a migration while the stack is running:** `docker compose exec api alembic upgrade head` (uvicorn --reload does not run migrations). Karma migration: `b8c9d0e1f2a3`.
- **v1 limits (accepted):** add-only (no removal); alt-farming is only blocked per-pair (karma has no reward so the incentive is low); the `karma_grant` ledger is not cleaned up (one row per pair).
