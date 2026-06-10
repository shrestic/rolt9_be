# Mini-games — Guide & Workflow

Three coin-betting games: **coinflip**, **over/under** (3-dice), **slots**. They are a coin sink (house edge ~5%) to fight inflation.

---

## 1. What this feature does

- Members bet coins on 3 games of chance. Win → get a payout, lose → lose the bet.
- **House edge ~5%**: on average players lose a little → coins are pulled out of the economy (balancing the coins earned from chat/daily/quest).
- **Dependency:** Currency enabled (bets/payouts are all coins).

---

## 2. For admins — Dashboard → server → Mini-games

| Field | Meaning | Default |
|---|---|---|
| **Enable** | Turn mini-games on/off | off |
| **Min bet** | Minimum bet | 10 |
| **Max bet** | Maximum bet | 10,000 |

The house edge (~5%) is fixed in code, not adjustable via the FE.

---

## 3. For members — Discord commands

| Command | What it does |
|---|---|
| `/game flip <bet> <Heads\|Tails>` | Flip a coin 50/50 → win ×1.9 |
| `/game overunder <bet> <Over\|Under>` | Sum of 3 dice; Under ≤10, Over ≥11 → win ×1.9 |
| `/game slots <bet>` | Slots: 3 matching = jackpot ×10, 2 matching = ×1.6 |

- The bet must be within min/max and ≤ your balance (else ❌).
- **3s cooldown/person/command** (anti-spam) → ⏳ if you click too fast.

Examples: `🎲 4+5+2=11 (Over) — 🎉 Win! +90 🪙 (balance 1,290)` · `🎰 💎💎💎 — 🎉 Win! +900 🪙` · `🪙 Tails — 😢 Lost 100 🪙 (balance 900)`.

---

## 4. Internals (for devs)

```
/game flip → MinigameCog (3s cooldown) → MinigameService._play
  ├─ enabled? bet ∈ [min,max]?
  ├─ WalletRepository.add_balance(-bet)   ← deduct the bet; insufficient → ValueError, NO play
  ├─ outcome = minigame_logic.play_*(rng, bet, choice)
  └─ win → add_balance(+payout)           ← same transaction
```

- **Pure logic** `minigame_logic.py`: takes an injected `random.Random` → deterministic tests (seeded). Multipliers give a ~5% house edge (coinflip/taixiu ×1.9, slots ×10/×1.6 — EV documented in the docstring).
- **Atomic & safe**: deduct the bet FIRST (guarded `add_balance`, never negative) → if the charge fails there's no play; credit the win in the same transaction → no coins created/lost.
- **Cooldown**: `@app_commands.checks.cooldown(1, 3.0)` in-memory (resets on bot restart) + `cog_app_command_error` renders ⏳.
- **Decoupled**: MinigameService uses `WalletRepository` directly (does not call CurrencyService).
- **No per-user table** — one round is just a wallet movement. Config: `guild_minigame_config` (enabled, min_bet, max_bet).

REST: GET/PUT `/guilds/{id}/minigame/settings` (gated by `require_managed_guild`).

---

## 5. Operation

- **Adding a migration while the stack is running:** `docker compose exec api alembic upgrade head`. Minigame migration: `c9d0e1f2a3b4`.
- **v1 limits (accepted):** RNG is `random.Random` (not cryptographic, fine for a fun game); the in-memory cooldown is lost on restart; the house edge is fixed at ~5%.
