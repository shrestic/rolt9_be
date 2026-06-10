# WC Predict — Per-server World Cup prediction league (design)

**Date:** 2026-06-02
**Status:** Locked via brainstorming. (Tracked copy of the original spec in `docs/superpowers/specs/`.)

## Goal (one sentence)

Each Discord server runs a "prediction league" for World Cup matches: the bot auto-pulls the
schedule from a free football API, posts match cards with flags + buttons, players predict; when a
match finishes the bot auto-scores it and updates the season leaderboard; at the end of each round
the bottom-of-the-table player gets AI-roasted + given a shaming nickname. **Honor only, NO virtual
currency, NO point deductions** — a wrong prediction just scores 0, you lose nothing.

## Why it's different from "regular betting"

There's no wallet/money/points-lost. This is an **adjudicated** tipping/fantasy league: you
accumulate points for correct predictions and race up the leaderboard; the drama seasoning is the
FUN punishment (nickname change + roast) for the loser, carried out by rolt9's savage AI.

## Bet scope (4 types) + scoring

Points by difficulty (default numbers, configurable in config/constants):

| Type | Description | Points when correct |
|---|---|---|
| **1X2** | Home win / draw / away win | 1 |
| **Over/Under** | Total goals Over/Under a line (default 2.5) | 1 |
| **Asian handicap** | The stronger team gives 0.5/1/1.5… (WHOLE/HALF lines ONLY, NO quarter-handicap half-win-half-loss in v1) | 2 |
| **Correct score** | Predict the exact final score | 5 |

Wrong = 0 points (never negative). One prediction per (person, match, bet type); **editable until kickoff**.

## Data source

**football-data.org free tier** (has the World Cup competition, ~10 req/min). Global key via env
(`FOOTBALL_DATA_API_KEY`). Fetches: match schedule (2 teams, UTC kickoff time), status, final score.
Error/rate-limit → skip the tick, retry (like SubscriptionCog). Postponed/rescheduled match → update
from the API; corrected results are rare → re-score.

## DB (new tables)

- **`wc_match`** (SHARED across all guilds): `id` (= API match id), `competition`, `stage`, `matchday`,
  `home_team`, `home_code`, `away_team`, `away_code`, `kickoff_at` (UTC, indexed), `status`
  (scheduled/in_play/finished), `home_score`, `away_score`, `ou_line` (default 2.5),
  `handicap_team` (home/away), `handicap_line`, `settled`, `created_at`, `updated_at`.
- **`wc_prediction`**: `id`, `guild_id` (FK guilds), `match_id` (FK wc_match), `user_discord_id`,
  `bet_type` (`1x2|ou|cs|ah`), `pick` (e.g. `home`/`over`/`2-1`/`favorite`), `points` (nullable),
  `created_at`. UNIQUE (`guild_id`,`match_id`,`user_discord_id`,`bet_type`). Index (`guild_id`,`match_id`).
- **`guild_wc_config`**: `guild_id` (PK/FK), `enabled`, `channel_id`, `shame_nick_prefix`
  (default `🤡 Non Tay — `), `created_at`, `updated_at`.
- **`wc_shame`**: `guild_id`, `user_discord_id`, `original_nick` (nullable), `applied_at`.

## Components

- **`services/wc/football_api.py`** — football-data.org client. Error → returns empty/None, doesn't raise.
- **`repositories/wc_match.py`, `wc_prediction.py`, `wc_config.py`** — data access.
- **`services/wc/scoring.py`** — PURE: `score(...)` → points.
- **`cogs/wc_sync.py`** — `tasks.loop`: (1) sync `wc_match` from the API; (2) post cards for
  upcoming matches; (3) `finished` matches not yet scored → score all predictions → write `points`.
  "posted"/"scored" flags.
- **`cogs/wc_predict.py`** — match cards (Embed: flags + team names + Vietnam time) + 1X2/Over-Under/
  handicap buttons, a "🎯 Predict score" button → modal, quick 1X2 via flag reactions, write/edit
  predictions, LOCK at kickoff. Commands `/wc-bxh`, `/wc-cua-toi`, `/wc-setup`.
- **Punishment** — a "ROUND" = `stage`/`matchday`; it ENDS when every match in the round is
  `finished`. The lowest-scoring player in the guild → AI roast + nickname change (prefix), saving the
  original nick; on the next round → restore the nick. Server owner / a role ≥ the bot → roast only,
  skip the nick change.

## AI integration

- **Roast the loser**: the AI generates a personalized savage line during punishment.
- **Bet advice**: "@rolt9 which team should I predict" → the agent uses `web_search` → gives a savage
  verdict (tool already available).
- **Predict by voice**: "@rolt9 I predict Brazil 2-1" → new `wc_predict` tool parses + records.
- **Card hot-take**: when posting a card, the AI adds a savage one-liner (optional, error → the card
  still posts).

## Configuration

`/wc-setup` (needs Manage Server): enable/disable, pick the channel, set the shaming nick prefix.
The bot needs **Manage Nicknames** to punish — without it, skip the nick change but still roast. The
FE dashboard page comes LATER (out of scope).

## Edge cases

- API error/limit → skip the tick, no crash. Postponed/rescheduled match → update `kickoff_at`.
- Result corrected after scoring (rare) → re-score. A member who leaves the server → keep their
  prediction, the leaderboard skips it if it can't resolve. Nick change: owner/a role higher than the
  bot → roast only. Adding then removing a flag → cancel the corresponding 1X2 prediction (only before
  kickoff).

## Out of scope (v1)

Quarter-ball handicap; BTTS / goalscorer / outright tournament winner; the FE dashboard page; betting
with currency/points that can be lost.
