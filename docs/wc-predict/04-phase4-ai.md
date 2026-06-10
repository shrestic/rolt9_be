# WC Predict — Phase 4: AI (bet advice / predict-by-voice / hot-take) (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Layer rolt9's flavor over WC Predict: (1) **predict by voice** — "@rolt9 I predict Brazil
2-1" → an agent tool parses + records into `wc_prediction`; (2) **bet advice** — "@rolt9 which team
should I predict" → the agent uses `web_search` (already available) + knows the WC context; (3) **card
hot-take** — the card is posted with a savage one-liner (optional; error/AI off → the card still posts).

**Architecture:** Add a `wc_predict` tool to the agent (tools/registry.py spec + a handler that writes
the DB). Bet advice only needs a persona nudge (web_search is already available). The hot-take = one
short `AIGateway.complete` call in the `wc_sync` cog when posting a card, passed into
`build_match_embed(hot_take=...)` (the param already exists from Phase 2). Every AI branch is wrapped in
try/except so it never breaks the main flow.

**Tech Stack:** AIGateway (`complete`/`complete_raw` tool-loop), tools/actions registry, pytest.
Depends on Phase 1+2 (+3 if you want a shared roast). **Read first:** `app/services/ai/tools/registry.py`,
`app/services/ai/actions/registry.py`, `app/services/ai/agent_service.py` to follow exactly how a tool
is declared + dispatched in the repo (the current spec + handler structure).

---

## File structure

| File | Responsibility | Test? |
|---|---|---|
| `app/services/wc/nl_predict.py` | Parse "predict <team> <score>/win/lose/over/under" → (bet_type, pick) + resolve match | ✅ unit |
| `app/services/ai/tools/registry.py` (modify) | Add the `wc_predict` tool spec + handler | per the repo's routing test |
| `app/services/ai/agent_service.py` (modify) | Nudge the WC context (bet advice + know the wc_predict tool) | — |
| `app/bot/cogs/wc_sync.py` (modify) | Generate a hot-take when posting a card (optional) | manual |
| `app/services/wc/hot_take.py` | build a 1-sentence hot-take prompt | ✅ unit (build) |

---

### Task 1: `nl_predict.py` — parse predictions by voice

**Files:** Create `app/services/wc/nl_predict.py`; Test `tests/unit/test_wc_nl_predict.py`.

Goal: from the sentence/arguments the agent has extracted (team name + intent), infer `(bet_type, pick)`.
Matching the TEAM → `match_id` is the handler's job (needs the DB). The pure function here only handles
bet/pick from the text.

- [ ] **Step 1: Test** `tests/unit/test_wc_nl_predict.py`:

```python
import pytest

from app.services.wc.nl_predict import parse_intent


@pytest.mark.parametrize("text,team_side,expected", [
    ("I predict Brazil 2-1", "home", ("cs", "2-1")),
    ("Brazil wins", "home", ("1x2", "home")),
    ("this one's a draw", None, ("1x2", "draw")),
    ("Argentina wins", "away", ("1x2", "away")),
    ("over", None, ("ou", "over")),
    ("under it", None, ("ou", "under")),
])
def test_parse_intent(text, team_side, expected):
    assert parse_intent(text, team_side=team_side) == expected


def test_unparseable_returns_none():
    assert parse_intent("yeah sure", team_side=None) is None
```

- [ ] **Step 2: FAIL → Step 3: `app/services/wc/nl_predict.py`**:

```python
"""Infer (bet_type, pick) from a player's words for WC. PURE — the agent handles matching team→match_id.

team_side = the position of the team the player mentioned in that match ('home'/'away'/None), determined
by the agent beforehand. Priority: score (cs) > over/under (ou) > win-lose-draw (1x2). Can't infer -> None.
"""
import re

_SCORE = re.compile(r"\b(\d{1,2})\s*[-:]\s*(\d{1,2})\b")


def parse_intent(text: str, *, team_side: str | None) -> tuple[str, str] | None:
    t = (text or "").lower()
    m = _SCORE.search(t)
    if m:
        return "cs", f"{int(m.group(1))}-{int(m.group(2))}"
    if "over" in t:
        return "ou", "over"
    if "under" in t:
        return "ou", "under"
    if "draw" in t or "tie" in t:
        return "1x2", "draw"
    if "win" in t or "beat" in t:
        if team_side in ("home", "away"):
            return "1x2", team_side
    if "lose" in t or "loses" in t:
        if team_side == "home":
            return "1x2", "away"
        if team_side == "away":
            return "1x2", "home"
    return None
```

- [ ] **Step 4: PASS → commit** `feat(wc): natural-language prediction intent parser`.

---

### Task 2: `wc_predict` tool for the agent

**Read `app/services/ai/tools/registry.py` first** to match exactly the existing spec + handler
structure (how tools like `remind`, `subscribe`, `forget` are declared, what the handler receives,
returns, and how it gets `session`/`guild`). Follow it exactly.

- [ ] **Step 1: Tool spec** (add alongside the other specs) — parameters:
  - `team` (string, required): the team name the player mentioned (e.g. "Brazil").
  - `intent` (string, required): the player's intent verbatim (e.g. "2-1", "win", "over") for
    `parse_intent` to handle.
  - Tool description: "Record the user's World Cup prediction for an upcoming match. Use when the user
    says something like 'I predict <team> <score/win/lose/over/under>'. Only record if an upcoming
    match for that team is found."

- [ ] **Step 2: Handler `wc_predict`** (following the pattern of the other handlers in the file):
  1. `guild = GuildRepository(session).get_by_discord_id(...)`.
  2. Find the upcoming match matching `team`: query `wc_match` with `status=scheduled`, `kickoff_at >= now`,
     name/code containing `team` (ilike) — take the nearest match. Not found → return "No upcoming match
     found for {team}." (report honestly, don't fabricate — per the repo's execute-then-report CRUD principle).
  3. Determine `team_side`: 'home' if it matches home_team/home_code, else 'away'.
  4. `res = parse_intent(intent, team_side=team_side)`; None → "Not sure what you're predicting
     (score/win/lose/over/under)?".
  5. Check the lock (`is_locked`) → "🔒 Bets are locked.".
  6. `WCPredictionRepository.upsert(guild.id, match.id, user_id, bet, pick)` → return a confirmation with
     the match name + bet (e.g. "✅ Recorded bet: Brazil 2-1 (Brazil vs Argentina).").

- [ ] **Step 3: Test routing with slang/colloquial phrasing** (per repo habit — probe the real agent in
  the container with many phrasings: "i call brazil 2 1", "brazil's winning this one", "over for tonight's
  match") to confirm the `wc_predict` tool is ACTUALLY called (not just chat). Record the probe results.

- [ ] **Step 4:** Lint + `.venv/bin/pytest -q` + commit `feat(wc): agent tool to record predictions by voice`.

---

### Task 3: Nudge the WC context (bet advice)

**Files:** Modify `app/services/ai/agent_service.py`.

- [ ] Add a short snippet to `_TOOL_NUDGE` (or the system): when the user asks "which team should I predict /
  the bet for match X" → USE `web_search` to look up real form/lineups then give a **savage** verdict
  (keep rolt9's voice), DON'T fabricate stats; when the user says "I predict ..." → call the `wc_predict`
  tool. Keep it brief (a long nudge dilutes the prompt). No separate test needed — verify via the Task 2/manual probe.
- [ ] Commit `feat(wc): nudge agent for WC tips + voice predictions`.

---

### Task 4: Card hot-take

**Files:** Create `app/services/wc/hot_take.py`; Modify `app/bot/cogs/wc_sync.py`.

- [ ] **Step 1: `app/services/wc/hot_take.py`** + test (build prompt contains the 2 team names):

```python
"""1-sentence hot-take prompt for a WC match card (rolt9's savage voice). Error/AI off -> cog skips it, the card still posts."""


def build_hot_take_system(persona: str | None) -> str:
    base = "You are savage rolt9. Give 1 SENTENCE of a teasing/funny comment about an upcoming match. Vietnamese, <= 25 words."
    return f"{base}\nPersona: {persona}" if persona else base


def build_hot_take_prompt(home: str, away: str) -> str:
    return f"Upcoming match: {home} vs {away}. Give exactly 1 savage hot-take sentence."
```

- [ ] **Step 2: In `_post_due_cards` (cog `wc_sync`)** before `channel.send`: try to generate the hot-take
  (wrapped in try/except ValueError + Exception, short timeout). Get `persona` from `AIConfigRepository`:
  ```python
  hot = None
  try:
      hot = await _gateway(session).complete(
          guild_discord_id=<discord_guild_id>,
          system=build_hot_take_system(persona),
          prompt=build_hot_take_prompt(match.home_team, match.away_team),
          max_tokens=80,
      )
  except Exception:  # noqa: BLE001 — AI off/error -> card still posts without a hot-take
      hot = None
  embed = build_match_embed(match, locked=False, hot_take=hot)
  ```
  > You need `discord_guild_id` (snowflake) here — map back from `cfg.guild_id` (UUID) via
  > `GuildRepository.get(...)`/`bot.get_guild`, or use `channel.guild.id`. The simplest:
  > `channel.guild.id` after the `get_channel`.
  > **Avoid burning tokens:** only generate the hot-take once per card (the card is posted only once anyway thanks to `wc_card`).

- [ ] **Step 3:** Lint + `.venv/bin/pytest -q` + commit `feat(wc): AI hot-take line on match cards`.

---

## Manual verification (real server, AI on + key present)

- [ ] "@rolt9 I predict Brazil 2-1" (+ a few slang variants) → the bot calls the tool, records the bet,
  confirms the correct match + score; check `wc_prediction`.
- [ ] "@rolt9 who should I pick for Brazil vs Argentina" → the bot searches the web then gives a verdict with evidence + a savage voice.
- [ ] Predict a team with no upcoming match → the bot reports "no match found" (DOESN'T fabricate).
- [ ] After kickoff → "I predict..." → the bot reports it's locked.
- [ ] A new match card gets an extra *hot-take* line; when AI is off/out of key → the card still posts normally, no error.

## Self-review

- **Phase 4 spec coverage:** predict-by-voice (tool) ✅; bet advice (web_search + nudge) ✅; hot-take ✅;
  every AI branch fail-safe (error → doesn't break the flow) ✅.
- **Type consistency:** `parse_intent` returns `(bet_type, pick)` matching `WCPredictionRepository.upsert` +
  `scoring.score`; `bet_type` ∈ `{1x2,ou,cs}` (ah is hard to express by voice → dropped in v1, only via
  buttons — note: if ah-by-voice is needed, extend `parse_intent` later).
- **Token/noise safety:** hot-take once per card; bet advice only when the user asks.
