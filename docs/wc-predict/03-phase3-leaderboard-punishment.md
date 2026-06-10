# WC Predict — Phase 3: Leaderboard + Nick-change punishment + AI roast (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** `/wc-bxh` (season leaderboard) + `/wc-cua-toi` (my bets). At the end of each ROUND, the
lowest-scoring player in the guild gets publicly AI-roasted + given a shaming nickname (original nick
saved); on the next round their nick is restored. Owner/a role ≥ the bot → roast only, skip the nick change.

**Architecture:** Round-splitting logic (`rounds.py`) + picking the loser are split out pure for
testing; the AI roast goes through the per-guild AIGateway; the nick change + permission guard are
Discord glue (following the existing guard in `actions/registry.py`). A `wc_round` table prevents
re-punishing a round.

**Tech Stack:** discord.py 2.4 (`member.edit(nick=...)`, app_commands), SQLAlchemy 2 async, Alembic,
AIGateway, pytest. Depends on Phase 1+2.

---

## File structure

| File | Responsibility | Test? |
|---|---|---|
| `app/services/wc/rounds.py` | `round_key(match)`, `completed_rounds(matches)` | ✅ unit |
| `app/services/wc/standings.py` | pick the loser from the leaderboard (filter to members still in the guild) | ✅ unit |
| `app/services/wc/roast_service.py` | build the system/prompt to roast the loser | ✅ unit (build prompt) |
| `app/models/wc_round.py` + repo + migration | `wc_round` table (punished round + who was punished) | — / ✅ repo |
| `app/bot/cogs/wc_predict.py` (modify) | add `/wc-bxh`, `/wc-cua-toi` | manual |
| `app/bot/cogs/wc_sync.py` (modify) | after settle → punish newly-completed rounds | manual |

---

### Task 1: `rounds.py` — split rounds + completed rounds

A "ROUND" = `stage` + `matchday` (e.g. `GROUP_STAGE:1`, `ROUND_OF_16:None`). A round ENDS when EVERY
match in that round is `settled`.

**Files:** Create `app/services/wc/rounds.py`; Test `tests/unit/test_wc_rounds.py`.

- [ ] **Step 1: Failing test** `tests/unit/test_wc_rounds.py`:

```python
from app.services.wc.rounds import completed_rounds, round_key


class _M:
    def __init__(self, stage, matchday, settled):
        self.stage, self.matchday, self.settled = stage, matchday, settled


def test_round_key():
    assert round_key(_M("GROUP_STAGE", 1, True)) == "GROUP_STAGE:1"
    assert round_key(_M("ROUND_OF_16", None, True)) == "ROUND_OF_16:-"


def test_completed_only_when_all_settled():
    ms = [
        _M("GROUP_STAGE", 1, True), _M("GROUP_STAGE", 1, True),   # full round -> completed
        _M("GROUP_STAGE", 2, True), _M("GROUP_STAGE", 2, False),  # 1 match not settled yet
    ]
    assert completed_rounds(ms) == {"GROUP_STAGE:1"}
```

- [ ] **Step 2: Run it red** → FAIL.

- [ ] **Step 3: `app/services/wc/rounds.py`**:

```python
"""Split matches into ROUNDS (stage+matchday) and determine completed rounds (all matches settled). PURE."""
from collections import defaultdict


def round_key(match) -> str:
    """A stable round key: 'STAGE:matchday' ('-' if matchday is None)."""
    md = match.matchday if match.matchday is not None else "-"
    return f"{match.stage}:{md}"


def completed_rounds(matches) -> set[str]:
    """The set of round_keys where EVERY match in that round is settled (and the round has at least 1 match)."""
    groups: dict[str, list] = defaultdict(list)
    for m in matches:
        if m.stage is None:
            continue
        groups[round_key(m)].append(m)
    return {k for k, ms in groups.items() if ms and all(m.settled for m in ms)}
```

- [ ] **Step 4: PASS** → commit `feat(wc): round grouping + completion detection`.

---

### Task 2: `standings.py` — pick the bottom player

**Files:** Create `app/services/wc/standings.py`; Test `tests/unit/test_wc_standings.py`.

The leaderboard (Phase 1 repo) returns `[(user_id, total)]` descending. The loser = the lowest score
AMONG members still in the guild; need ≥ 2 players to punish (to avoid punishing the only player). A
tie for last → who to pick? → pick the smallest user_id (stable) or skip punishment on a multi-way tie
— decision: punish 1 person (the smallest) for simplicity; noted in code.

- [ ] **Step 1: Test** `tests/unit/test_wc_standings.py`:

```python
from app.services.wc.standings import pick_loser


def test_pick_loser_lowest_among_members():
    lb = [(1, 10), (2, 3), (3, 8)]  # descending, sorted by the repo; this tests the min-pick logic
    members = {1, 2, 3}
    assert pick_loser(lb, members) == 2


def test_skip_when_fewer_than_two_players():
    assert pick_loser([(1, 5)], {1}) is None
    assert pick_loser([], set()) is None


def test_ignore_users_left_guild():
    lb = [(1, 10), (2, 1), (3, 8)]
    assert pick_loser(lb, {1, 3}) == 3  # user 2 has left -> ignored
```

- [ ] **Step 2: FAIL → Step 3: `app/services/wc/standings.py`**:

```python
"""Pick the bottom player to punish (pure). Filter to members still in the guild; need >= 2 players."""


def pick_loser(leaderboard: list[tuple[int, int]], member_ids: set[int]) -> int | None:
    """leaderboard = [(user_id, total)] (any order). Return the user_id with the lowest score that IS in
    member_ids, None if < 2 valid players. Tie for last -> pick the smallest user_id (stable)."""
    valid = [(uid, pts) for uid, pts in leaderboard if uid in member_ids]
    if len(valid) < 2:
        return None
    low = min(pts for _, pts in valid)
    return min(uid for uid, pts in valid if pts == low)
```

- [ ] **Step 4: PASS → commit** `feat(wc): pick lowest scorer (filter members, need 2+)`.

---

### Task 3: `roast_service.py` — roast prompt

**Files:** Create `app/services/wc/roast_service.py`; Test `tests/unit/test_wc_roast_service.py`.

- [ ] **Step 1: Test** (only test that the built prompt contains the name + points + WC context):

```python
from app.services.wc.roast_service import build_roast_prompt, build_roast_system


def test_prompt_has_context():
    sys = build_roast_system("savage persona")
    p = build_roast_prompt(name="Khoi", points=2, round_label="group stage matchday 1")
    assert "Khoi" in p and "2" in p and "group stage" in p
    assert "persona" in sys.lower() or len(sys) > 0
```

- [ ] **Step 2: FAIL → Step 3: `app/services/wc/roast_service.py`**:

```python
"""Prompt for the AI to roast the WC bottom player. Keep rolt9's savage voice; 1-2 sentences, no heavy profanity."""


def build_roast_system(persona: str | None) -> str:
    base = (
        "You are rolt9 — a savage, cheeky but witty Discord bot. Task: SHORT roast (1-2 sentences) of "
        "the person who predicted football worst this round. Funny, friendly teasing, NO heavy "
        "insults/discrimination. Vietnamese, emoji allowed."
    )
    return f"{base}\n\nServer persona: {persona}" if persona else base


def build_roast_prompt(*, name: str, points: int, round_label: str) -> str:
    return (
        f"Roast {name} for predicting football worst in {round_label}, scoring only {points} points. "
        f"1-2 sentences, mention the name {name}."
    )
```

- [ ] **Step 4: PASS → commit** `feat(wc): roast prompt builder for bottom scorer`.

---

### Task 4: `wc_round` table + repo + migration

Prevent re-punishing a round + know who is currently shamed so the nick can be restored next round.

**Files:** `app/models/wc_round.py`, `app/repositories/wc_round.py`,
`alembic/versions/<ts>_wc_round.py`, modify `app/db/base.py`; Test `tests/unit/test_wc_round_repo.py`.

- [ ] Model `WCRound`: `id`, `guild_id` (FK), `round_key` (String), `loser_user_id` (BigInteger,
  nullable), `punished_at`. UNIQUE(`guild_id`,`round_key`).
- [ ] Repo `WCRoundRepository`: `is_punished(guild_id, round_key) -> bool`,
  `record(guild_id, round_key, loser_user_id)`, `last_loser(guild_id) -> int | None` (the most
  recently punished person, for restoring the nick).
- [ ] Migration `revision=e2dc0round003`, `down_revision` = the current head (verify `alembic heads`).
- [ ] Test the repo (is_punished False→record→True; last_loser). Apply the migration. Lint + commit
  `feat(wc): wc_round table + repo (track punished rounds)`.

(The code skeleton is identical to `wc_card` Task 3 in Phase 2 — just rename the columns; infer it yourself.)

---

### Task 5: `/wc-bxh` + `/wc-cua-toi`

**Glue — manual.** Add 2 commands to the `app_commands.Group("wc")` in `wc_predict.py`.

- [ ] **`/wc-bxh`**: `defer()` → `session_scope` → `lb = await WCPredictionRepository(session).leaderboard(guild.id)`
  → render the top-N Embed: resolve names via `interaction.guild.get_member(uid)` (None → "(left)"),
  skip those who left if desired. Footer "World Cup season". `followup.send(embed=...)`.
- [ ] **`/wc-cua-toi`**: list `interaction.user`'s predictions (via `for_user_match` per match or add a
  repo method `for_user(guild_id, user_id)`), with the scored points / "awaiting match". Ephemeral.
- [ ] Render helper (`render_leaderboard(rows, name_of) -> str`) split out pure → small test
  `tests/unit/test_wc_render.py` (sort/format/numbering 🥇🥈🥉).
- [ ] Lint + `.venv/bin/pytest -q` + commit `feat(wc): /wc-bxh + /wc-cua-toi commands`.

> Add `WCPredictionRepository.for_user(self, guild_id, user_id)` (like `for_user_match` minus the match
> condition) if needed for `/wc-cua-toi`; add a test.

---

### Task 6: Punish newly-completed rounds (cog `wc_sync`)

**Glue — manual.** After `settle_finished` each tick, check for newly-completed rounds → punish.

- [ ] **Step 1: Add a method `_punish_completed_rounds(self)`** to `WCSyncCog`, called after settle in
  `wc_tick`. The flow (per enabled guild):
  1. Get all `WCMatch` (`mrepo.all()` — add the method) → `done = completed_rounds(matches)`.
  2. For each `rk in done` not yet `WCRoundRepository.is_punished(guild.id, rk)`:
     - `lb = leaderboard(guild.id)`; `member_ids = {m.id for m in discord_guild.members}`;
       `loser = pick_loser(lb, member_ids)`. None → still `record` (mark as processed, punish no one).
     - **Restore the previous round's punished member's nick:** `prev = WCRoundRepository.last_loser(guild.id)`;
       if there's a `wc_shame` row for prev → `member.edit(nick=original_nick)` (permission-guarded) → delete the shame row.
     - **Roast + change the loser's nick:** get `cfg.persona` (via `AIConfigRepository`), call
       `AIGateway.complete(guild_discord_id=..., system=build_roast_system(persona),
       prompt=build_roast_prompt(name=member.display_name, points=..., round_label=rk))` in a
       try/except ValueError. Send the roast to `cfg.channel_id`.
     - **Change the nick** (guard, per `actions/registry.py`): skip if
       `member.id == discord_guild.owner_id` or `discord_guild.me.top_role <= member.top_role`
       or no `discord_guild.me.guild_permissions.manage_nicknames` → roast only, send a gentle note. Otherwise:
       save `wc_shame(guild_id, user_id, original_nick=member.nick)` then
       `await member.edit(nick=f"{cfg.shame_nick_prefix}{member.display_name}"[:32])`.
     - `WCRoundRepository.record(guild.id, rk, loser_user_id=loser)`.
  3. Wrap every `member.edit` / `channel.send` in `try/except discord.DiscordException`.

- [ ] **Step 2:** Add `WCMatchRepository.all()` + test. `.venv/bin/pytest -q` green.
- [ ] **Step 3:** Lint + commit `feat(wc): punish bottom scorer per completed round (roast + nick)`.

---

## Manual verification (real server)

- [ ] Seed/wait for one round with all matches `settled`. The bot posts the loser roast in the correct
  channel, mentioning the right name + points.
- [ ] The loser's nick changes to `🤡 Non Tay — <name>` (if the bot has enough permission + they're not the owner/a high role).
- [ ] An owner/a role ≥ the bot who finishes bottom → ONLY roast, no nick change, with a gentle note.
- [ ] The NEXT round completes → the previous round's punished member's nick is RESTORED; the new round's loser is shamed.
- [ ] An already-punished round is not re-punished (check `wc_round`).
- [ ] `/wc-bxh` sorts correctly descending; `/wc-cua-toi` lists bets + points/awaiting.
- [ ] < 2 players → no one is punished (the round is still marked as processed).

## Self-review

- **Phase 3 spec coverage:** leaderboard ✅; my-bets ✅; punish the bottom player with nick change +
  save/restore the original nick ✅; AI roast ✅; owner/role/permission guard ✅; prevent re-punishing
  ✅; "round" = stage+matchday ✅.
- **Type consistency:** `round_key` used consistently across `rounds.py`/`wc_round`/cog; `pick_loser`
  consumes the output of `leaderboard()`; the nick prefix comes from `guild_wc_config.shame_nick_prefix`.
