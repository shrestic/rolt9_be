# Server Pet — Guide & Workflow

Each server raises **one shared pet** (a collective Tamagotchi). The whole community feeds/plays together to keep the pet full & happy and grow it up.

---

## 1. What this feature does

- **1 pet/server**, everyone pitches in to raise it.
- 2 stats — **Hunger** + **Happiness**, each 0–100, **decaying over time**.
- **Feed** (costs coins) → +Hunger. **Play** (free, 1h cooldown/person) → +Happiness.
- Each care action → pet +XP → **levels up → evolves** (🥚 Egg → 🐣 Hatchling → 🐤 Juvenile → 🦅 Adult).
- Neglect → bars drop to 0, the pet shows a sad face 😿 but **doesn't die** — caring again revives it.
- **Pure emotion/show-off** — the pet grants no buffs; the joy is raising it together.

> **Dependency:** Currency enabled (feeding costs coins). Play still works when currency is off.

---

## 2. For admins — Dashboard → server → Pet

| Field | Meaning | Default |
|---|---|---|
| **Enabled** | Turn the pet on/off | off |
| **Name** | Pet name (1–32 chars) | "Pet" |
| **Feed cost** | Coins per feed | 10 |
| **Feed amount** | +Hunger per feed (1–100) | 30 |
| **Play amount** | +Happiness per play (1–100) | 30 |
| **Decay per day** | How much each bar drops /day (0–100) | 20 |

Decay 20/day means a full bar (100) reaches 0 after ~5 days with no one caring for it.

---

## 3. For members — Discord commands

| Command | What it does |
|---|---|
| `/pet status` | View the pet: stage emoji + mood, the 2 Hunger/Happiness bars, level |
| `/pet feed` | Feed (costs coins) → +Hunger. Insufficient coins → ❌ |
| `/pet play` | Play (free, wait 1h between plays) → +Happiness |

Level-ups / evolutions are reported right in the feed/play reply: "🎉 reached Lv X" / "✨ evolved into …".

---

## 4. Internals (for devs)

```
/pet feed → PetCog → PetService.feed
  ├─ settle decay (by hours since last_decay_at, floor 0)
  ├─ WalletRepository.add_balance(-feed_cost)   ← insufficient → ValueError, bars UNCHANGED
  ├─ hunger = min(100, hunger + feed_amount); xp += 5
  └─ save_state(..., last_decay_at=now)

/pet play → 1h cooldown (PetCooldownRepository.try_play, atomic) → settle → +Happiness → save

/pet status / REST GET status → settle (COMPUTE, no write) → return
```

- **Lazy decay**: computed on read/interaction, **no background job**. `last_decay_at` only advances on feed/play; a read always computes relative to it → the display is always correct, and GET doesn't write (no side-effect).
- **Atomic**: `try_play` is a guarded UPDATE (cooldown in the WHERE) → the cooldown can't be bypassed; feed deducts coins via the guarded `add_balance` → never negative.
- **Safe**: deduct coins BEFORE adding Hunger → if the charge fails the bar doesn't increase. Both run in the same transaction (`session_scope`) → rolled back together.
- **Pure level/stage**: `pet_logic.pet_level(xp)` (50 XP/level), `stage_for(level)` (thresholds 1/5/15/30), `mood_for` (avg 70/40/10).
- **Tables**: `guild_pet` (state+config, 1 row/guild), `user_pet_cooldown` (per-user play cooldown).

REST: GET/PUT `/guilds/{id}/pet/settings`, GET `/guilds/{id}/pet/status` (gated by `require_managed_guild`).

---

## 5. Operation

- **Adding a migration while the stack is running:** `docker compose exec api alembic upgrade head` (uvicorn --reload does NOT run migrations). Pet migration: `a7b8c9d0e1f2`.
- **v1 limits (accepted):** the pet doesn't die; no buffs (no farming exploit); decay is computed lazily; alt-farming play is harmless (no reward).
