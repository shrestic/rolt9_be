# WC Predict — Per-server World Cup prediction league

The set of implementation plans for the **WC Predict** feature for rolt9 (a Discord bot). Each server
runs its own "prediction league" for World Cup matches: the bot pulls the schedule from a free
football API, posts match cards with flags + buttons, players predict; when a match finishes the bot
auto-scores it and updates the season leaderboard; at the end of each round the bottom-of-the-table
player gets AI-roasted + given a shaming nickname. **Honor only, NO virtual currency, NO point
deductions** — a wrong prediction just scores 0.

> This file + the plans in this folder are **working documents** (readable on any machine that has
> cloned the repo). Stick to the repo patterns excerpted in each plan. Stack: Python 3.12, FastAPI,
> SQLAlchemy 2 async, Alembic, discord.py 2.4, pytest, AIGateway (BYO-key per-guild), football-data.org.

## Phase map

| Phase | File | Content | Status |
|---|---|---|---|
| — | [`00-spec.md`](00-spec.md) | Original design spec (locked) | ✅ |
| 1 | (code already in repo) | Foundation: scoring + models + repos + API client | ✅ **DONE** (merged into `feat/claw-agent`) |
| 2 | [`02-phase2-discord.md`](02-phase2-discord.md) | Sync cog (loop to pull matches + score), match cards (flags + buttons + modal + flag reactions), `/wc-setup` | ⏳ TODO |
| 3 | [`03-phase3-leaderboard-punishment.md`](03-phase3-leaderboard-punishment.md) | Leaderboard (`/wc-bxh`, `/wc-cua-toi`) + nick-change punishment + AI roast of the loser | ⏳ TODO |
| 4 | [`04-phase4-ai.md`](04-phase4-ai.md) | AI: bet advice / predict-by-voice (agent tool) / card hot-take | ⏳ TODO |

## What Phase 1 already provides (foundation — don't redo)

Already coded + tested + pushed on the `feat/claw-agent` branch:

- **`app/services/wc/scoring.py`** — `POINTS = {"1x2": 1, "ou": 1, "ah": 2, "cs": 5}` and
  `score(bet_type, pick, *, home_score, away_score, ou_line=None, handicap_team=None, handicap_line=None) -> int`.
  Pure, no I/O. Wrong/push = 0. Asian handicap v1 only whole/half lines (no quarter-handicap).
- **Models** (`app/models/`): `wc_match` (PK = API match id, shared across all guilds),
  `wc_prediction` (UNIQUE `guild_id,match_id,user_discord_id,bet_type`), `guild_wc_config`
  (`enabled`/`channel_id`/`shame_nick_prefix` default `"🤡 Non Tay — "`), `wc_shame`
  (`original_nick`). Registered in `app/db/base.py`. Migration `c0ffee0wc001`.
- **Repos** (`app/repositories/`): `WCMatchRepository` (`upsert`/`finished_unsettled`/
  `mark_settled`/`get`), `WCPredictionRepository` (`upsert`/`for_match`/`for_user_match`/
  `set_points`/`leaderboard`), `WCConfigRepository` (`get`/`get_or_create`/`upsert`/`all_enabled`).
- **`app/services/wc/football_api.py`** — `fetch_wc_matches() -> list[dict]` calls
  football-data.org `/v4/competitions/WC/matches`, maps fields, error/missing key → `[]` (no raise).
  Env key `FOOTBALL_DATA_API_KEY` (already added to `app/core/config.py`).

Phase 1 tests: `tests/unit/test_wc_scoring.py`, `test_wc_models.py`, `test_wc_repos.py`,
`test_wc_football_api.py` — all pass (23 tests).

## Before running for real (needed for Phase 2)

1. Register for free at <https://www.football-data.org/> and get an API token.
2. Put it in the env: `FOOTBALL_DATA_API_KEY=<token>` (in `.env` / compose env). Empty = sync off, safe.
3. Free tier ~10 requests/min — a sync loop every 2–5 min/tick is plenty.

## Common conventions when coding (verified in the repo)

- **Cogs do NOT use `setup(bot)`/`load_extension`.** Register manually in
  `app/bot/client.py` → `setup_hook()` with `await self.add_cog(XxxCog(self, self.discord_io))`,
  then `await self.tree.sync()` at the end (already present).
- **DB session:** `from app.db.session import session_scope` then `async with session_scope() as session:`
  (auto-commits on exit, rolls back on error). Repos are flush-only, commit happens at the boundary.
- **Map guild:** `discord.Guild.id` (snowflake) → internal UUID via
  `await GuildRepository(session).get_by_discord_id(int(guild.id))` → `.id` is the UUID used for the FK.
- **AIGateway per-guild:** build a fresh one in the session (see `_gateway(session)` in `subscription.py`),
  call `await gw.complete(guild_discord_id=..., system=..., prompt=...)`. Error (AI off/missing key/over
  budget/empty) → raises `ValueError`; always `try/except ValueError` and skip/`❌ {exc}`.
- **Loop cog:** `@tasks.loop(...)`, start in `cog_load`, cancel in `cog_unload`,
  `@loop.before_loop` → `await self.bot.wait_until_ready()`. Wrap the loop body in
  `try/except Exception` so one failing tick doesn't kill the loop.
- **Slash command:** `@app_commands.command(...)` or `app_commands.Group(name=..., guild_only=True)`;
  check admin permission with `if not interaction.user.guild_permissions.manage_guild: ... return`
  (see `agent.py claw-lore-clear`). `await interaction.response.defer()` then `followup.send(...)`.
- **Lint + test before every commit:** `.venv/bin/ruff format <files>` → `.venv/bin/ruff check <files>`
  → `.venv/bin/pytest -q`. Commit messages follow Conventional Commits (commitizen pre-commit), ending
  with the line `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- **Cog/Discord-glue has no unit-test infrastructure** in the repo (only services/pure code are tested).
  So the plans pull the **pure logic/service** parts out for unit-testing, while the **Discord glue** is
  verified manually on a real server (the checklist at the end of each plan).
