# WC Predict — Phase 2: Sync loop + Match cards + /wc-setup (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (or
> executing-plans) to run this plan task-by-task. Steps have a `- [ ]` checkbox.

**Goal:** The bot auto-pulls the World Cup schedule on a tick, posts match cards with flags + buttons
+ a score modal + quick flag-prediction into the channel of each enabled server, writes/edits
predictions until kickoff, and auto-scores when a match finishes. Admins enable/configure via
`/wc-setup`.

**Architecture:** Pull the **pure logic/service** (flags, card rendering, sync+settle) out for
unit-testing; the **Discord glue** (cog loop, View/Modal/reaction, slash command) is verified
manually. Match cards use a **persistent view** (`discord.ui.DynamicItem`, discord.py 2.4) so buttons
survive restarts; the `custom_id` encodes `bet_type:pick:match_id`. Add a `wc_card` table to know
which cards have been posted (prevent re-posting) + map message ↔ match for reactions.

**Tech Stack:** discord.py 2.4 (`tasks.loop`, `app_commands`, `ui.View/Modal/DynamicItem`,
`on_raw_reaction_add/remove`), SQLAlchemy 2 async, Alembic, pytest. The Phase 1 foundation is in place.

**Phase 1 dependencies:** `app.services.wc.scoring.score/POINTS`, `app.services.wc.football_api.fetch_wc_matches`,
`WCMatchRepository`, `WCPredictionRepository`, `WCConfigRepository`, models `WCMatch/WCPrediction/GuildWCConfig`.

---

## File structure

| File | Responsibility | Test? |
|---|---|---|
| `app/services/wc/flags.py` | Team code (tla/code) → flag emoji | ✅ unit |
| `app/services/wc/cards.py` | Render the match-card Embed + Vietnam-time / bet-label / lock helpers | ✅ unit (pure parts) |
| `app/models/wc_card.py` | `wc_card` table: posted cards (guild,match,channel,message) | — |
| `app/repositories/wc_card.py` | `wc_card` data access | ✅ unit |
| `alembic/versions/<ts>_wc_card.py` | `wc_card` table migration | — |
| `app/services/wc/sync_service.py` | `sync_matches` + `settle_finished` (pure-DB orchestration) | ✅ unit |
| `app/bot/cogs/wc_predict.py` | Button View + score Modal + quick-1X2 reactions + write/edit bets + `/wc-setup` | manual |
| `app/bot/cogs/wc_sync.py` | `tasks.loop`: sync → post cards → settle | manual |
| `app/bot/client.py` | Register the 2 cogs + persistent dynamic items (edit `setup_hook`) | manual |

**`pick` convention:** `1x2` → `home|draw|away`; `ou` → `over|under` (line = `match.ou_line`);
`ah` → `favorite|underdog` (team/line = `match.handicap_team`/`handicap_line`); `cs` → the string `"H-A"`.

---

### Task 1: Flags — team code → flag emoji

**Files:** Create `app/services/wc/flags.py`; Test `tests/unit/test_wc_flags.py`.

football-data.org returns `tla` (a 3-char FIFA code, e.g. `BRA`). Unicode flag emoji need the ISO-2
code (`BR`→🇧🇷). We map FIFA→flag with a dict for the WC countries; missing → 🏳️.

- [ ] **Step 1: Write a failing test** `tests/unit/test_wc_flags.py`:

```python
from app.services.wc.flags import flag


def test_known_codes():
    assert flag("BRA") == "🇧🇷"
    assert flag("ARG") == "🇦🇷"
    assert flag("FRA") == "🇫🇷"


def test_case_insensitive_and_unknown():
    assert flag("bra") == "🇧🇷"
    assert flag("ZZZ") == "🏳️"
    assert flag(None) == "🏳️"
```

- [ ] **Step 2: Run it red** — `.venv/bin/pytest tests/unit/test_wc_flags.py -q` → FAIL (ModuleNotFound).

- [ ] **Step 3: Write `app/services/wc/flags.py`** (ISO-2 → flag via regional indicators; map FIFA→ISO2):

```python
"""Team code (FIFA tla, e.g. 'BRA') -> flag emoji. Missing code -> white flag 🏳️.

football-data.org returns a 3-char tla; flag emoji need ISO-3166 alpha-2. The dict below covers the
common WC teams; extend as needed. flag() tolerates None/unknown codes (returns 🏳️) so it never
breaks a card.
"""

# FIFA tla -> ISO-2. Extend gradually as new teams appear.
_FIFA_TO_ISO2 = {
    "BRA": "BR", "ARG": "AR", "FRA": "FR", "ENG": "GB", "ESP": "ES", "GER": "DE",
    "POR": "PT", "NED": "NL", "BEL": "BE", "ITA": "IT", "CRO": "HR", "URU": "UY",
    "USA": "US", "MEX": "MX", "CAN": "CA", "JPN": "JP", "KOR": "KR", "AUS": "AU",
    "MAR": "MA", "SEN": "SN", "GHA": "GH", "CMR": "CM", "NGA": "NG", "EGY": "EG",
    "SUI": "CH", "DEN": "DK", "POL": "PL", "SRB": "RS", "WAL": "GB", "SCO": "GB",
    "QAT": "QA", "KSA": "SA", "IRN": "IR", "CRC": "CR", "ECU": "EC", "COL": "CO",
    "CHI": "CL", "PER": "PE", "PAR": "PY", "TUN": "TN", "ALG": "DZ", "CIV": "CI",
    "NOR": "NO", "SWE": "SE", "AUT": "AT", "TUR": "TR", "UKR": "UA", "GRE": "GR",
}


def flag(code: str | None) -> str:
    """Return the flag emoji for a team code (FIFA tla or ISO-2). No match -> 🏳️."""
    if not code:
        return "🏳️"
    c = code.strip().upper()
    iso2 = _FIFA_TO_ISO2.get(c, c if len(c) == 2 else "")
    if len(iso2) != 2 or not iso2.isalpha():
        return "🏳️"
    # Join 2 regional indicators: 'A' (0x41) -> 0x1F1E6
    return "".join(chr(0x1F1E6 + (ord(ch) - ord("A"))) for ch in iso2)
```

- [ ] **Step 4: Run it green** — `.venv/bin/pytest tests/unit/test_wc_flags.py -q` → PASS.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff format app/services/wc/flags.py tests/unit/test_wc_flags.py
.venv/bin/ruff check app/services/wc/flags.py
git add app/services/wc/flags.py tests/unit/test_wc_flags.py
git commit -F - <<'EOF'
feat(wc): flag emoji helper (FIFA code -> flag, graceful)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

### Task 2: Cards — render the match card + helpers

**Files:** Create `app/services/wc/cards.py`; Test `tests/unit/test_wc_cards.py`.

- [ ] **Step 1: Write a failing test** `tests/unit/test_wc_cards.py`:

```python
from datetime import UTC, datetime, timedelta

from app.models.wc_match import WCMatch
from app.services.wc.cards import handicap_label, is_locked, ou_label, vn_time


def _m(**kw):
    base = dict(
        id=1, competition="WC", home_team="Brazil", home_code="BRA",
        away_team="Argentina", away_code="ARG",
        kickoff_at=datetime(2026, 6, 20, 12, 0, tzinfo=UTC), status="scheduled",
        ou_line=2.5, handicap_team="home", handicap_line=1.0,
    )
    base.update(kw)
    return WCMatch(**base)


def test_vn_time_is_utc_plus_7():
    # 12:00 UTC -> 19:00 Vietnam time
    assert "19:00" in vn_time(datetime(2026, 6, 20, 12, 0, tzinfo=UTC))


def test_is_locked_at_kickoff():
    m = _m()
    assert is_locked(m, m.kickoff_at - timedelta(minutes=1)) is False
    assert is_locked(m, m.kickoff_at) is True
    assert is_locked(m, m.kickoff_at + timedelta(minutes=1)) is True


def test_ou_label_shows_line():
    assert "2.5" in ou_label(_m())


def test_handicap_label_names_favorite():
    # home gives 1.0 -> Brazil is the favorite
    assert "Brazil" in handicap_label(_m())
    assert "1" in handicap_label(_m())
```

- [ ] **Step 2: Run it red** → FAIL.

- [ ] **Step 3: Write `app/services/wc/cards.py`** (pure helpers + Embed builder):

```python
"""Render the WC match card (Embed) + pure helpers (Vietnam time, bet labels, lock at kickoff).

The pure parts (vn_time/is_locked/ou_label/handicap_label) are split out for unit-testing;
build_match_embed combines them into a discord.Embed. NO I/O calls.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

import discord

from app.models.wc_match import WCMatch
from app.services.wc.flags import flag

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def vn_time(dt: datetime) -> str:
    """Kickoff time in Vietnam time, e.g. '19:00 20/06'."""
    return dt.astimezone(VN_TZ).strftime("%H:%M %d/%m")


def is_locked(match: WCMatch, now: datetime) -> bool:
    """Lock bets once kickoff is reached/passed."""
    return now >= match.kickoff_at


def ou_label(match: WCMatch) -> str:
    return f"Over/Under {match.ou_line:g}"


def handicap_label(match: WCMatch) -> str:
    """Handicap label, e.g. 'Brazil -1' (favorite + line)."""
    if match.handicap_team not in ("home", "away") or match.handicap_line is None:
        return "Handicap (not set)"
    fav = match.home_team if match.handicap_team == "home" else match.away_team
    return f"{fav} -{match.handicap_line:g}"


def title(match: WCMatch) -> str:
    return f"{flag(match.home_code)} {match.home_team}  vs  {match.away_team} {flag(match.away_code)}"


def build_match_embed(match: WCMatch, *, locked: bool, hot_take: str | None = None) -> discord.Embed:
    """Match-card Embed: title with flags, Vietnam time, the bets, lock state. hot_take (Phase 4) optional."""
    desc_lines = [f"🕐 **{vn_time(match.kickoff_at)}** (Vietnam time)"]
    if match.stage:
        desc_lines.append(f"🏟️ {match.stage}")
    if hot_take:
        desc_lines.append(f"\n💬 *{hot_take}*")
    embed = discord.Embed(title=title(match), description="\n".join(desc_lines), color=0x1FAA59)
    embed.add_field(name="1X2", value=f"{match.home_team} / Draw / {match.away_team}", inline=False)
    embed.add_field(name="Over/Under", value=ou_label(match), inline=True)
    embed.add_field(name="Handicap", value=handicap_label(match), inline=True)
    embed.set_footer(
        text="🔒 Bets locked" if locked else "Press a button to predict • flag reaction = quick 1X2 • locks at kickoff"
    )
    return embed
```

- [ ] **Step 4: Run it green** → PASS.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff format app/services/wc/cards.py tests/unit/test_wc_cards.py
.venv/bin/ruff check app/services/wc/cards.py
git add app/services/wc/cards.py tests/unit/test_wc_cards.py
git commit -F - <<'EOF'
feat(wc): match-card render + pure helpers (vn time, labels, lock)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

### Task 3: `wc_card` table + repo + migration

Track posted cards by (guild, match) to (a) avoid re-posting, (b) map message_id → match for
reactions, (c) update/lock the card at kickoff.

**Files:** Create `app/models/wc_card.py`, `app/repositories/wc_card.py`,
`alembic/versions/<timestamp>_wc_card.py`; Modify `app/db/base.py`; Test `tests/unit/test_wc_card_repo.py`.

- [ ] **Step 1: Write a failing test** `tests/unit/test_wc_card_repo.py`:

```python
import uuid
from datetime import UTC, datetime

import pytest

from app.models.guild import Guild
from app.models.wc_match import WCMatch
from app.repositories.wc_card import WCCardRepository


async def _seed(s):
    gid = uuid.uuid4()
    s.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))
    s.add(WCMatch(id=7, home_team="A", away_team="B",
                  kickoff_at=datetime(2026, 6, 20, tzinfo=UTC), status="scheduled"))
    await s.commit()
    return gid


@pytest.mark.asyncio
async def test_record_and_lookup(db_session):
    gid = await _seed(db_session)
    repo = WCCardRepository(db_session)
    assert await repo.exists(gid, 7) is False
    await repo.record(gid, 7, channel_id=100, message_id=999)
    await db_session.commit()
    assert await repo.exists(gid, 7) is True
    card = await repo.by_message(999)
    assert card is not None and card.match_id == 7 and card.guild_id == gid
    assert await repo.mark_locked(gid, 7) is None  # no error when called
    await db_session.commit()
```

- [ ] **Step 2: Run it red** → FAIL.

- [ ] **Step 3: Model `app/models/wc_card.py`**:

```python
"""Table `wc_card` — the card posted for one (guild, match): to prevent re-posting + map reactions."""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class WCCard(Base):
    __tablename__ = "wc_card"
    __table_args__ = (UniqueConstraint("guild_id", "match_id", name="uq_wc_card"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    guild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    match_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("wc_match.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 4: Repo `app/repositories/wc_card.py`**:

```python
"""Data access for wc_card (posted cards per guild/match)."""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.wc_card import WCCard


class WCCardRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def exists(self, guild_id: uuid.UUID, match_id: int) -> bool:
        res = await self.session.execute(
            select(WCCard.id).where(WCCard.guild_id == guild_id, WCCard.match_id == match_id)
        )
        return res.scalar_one_or_none() is not None

    async def record(self, guild_id: uuid.UUID, match_id: int, *, channel_id: int, message_id: int) -> WCCard:
        row = WCCard(guild_id=guild_id, match_id=match_id, channel_id=channel_id, message_id=message_id)
        self.session.add(row)
        await self.session.flush()
        return row

    async def by_message(self, message_id: int) -> WCCard | None:
        res = await self.session.execute(select(WCCard).where(WCCard.message_id == message_id))
        return res.scalar_one_or_none()

    async def unlocked_cards(self) -> list[WCCard]:
        res = await self.session.execute(select(WCCard).where(WCCard.locked.is_(False)))
        return list(res.scalars().all())

    async def mark_locked(self, guild_id: uuid.UUID, match_id: int) -> None:
        res = await self.session.execute(
            select(WCCard).where(WCCard.guild_id == guild_id, WCCard.match_id == match_id)
        )
        row = res.scalar_one_or_none()
        if row is not None:
            row.locked = True
        await self.session.flush()
```

- [ ] **Step 5: Register in `app/db/base.py`** — add the line (keep alphabetical order with the other wc imports):

```python
from app.models.wc_card import WCCard  # noqa: F401
```

- [ ] **Step 6: Migration** — `down_revision` = the CURRENT head (run `docker compose exec -T api alembic heads`
  to get it; at plan-writing time the Phase 1 head is `c0ffee0wc001`, BUT verify). File
  `alembic/versions/<timestamp>_wc_card.py`:

```python
"""WC Predict Phase 2: wc_card table

Revision ID: d1ce0card002
Revises: c0ffee0wc001
Create Date: ...
"""
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "d1ce0card002"
down_revision: Union[str, None] = "c0ffee0wc001"  # VERIFY = alembic heads
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wc_card",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("guild_id", UUID(as_uuid=True), sa.ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("match_id", sa.BigInteger(), sa.ForeignKey("wc_match.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("guild_id", "match_id", name="uq_wc_card"),
    )
    op.create_index("ix_wc_card_guild_id", "wc_card", ["guild_id"])
    op.create_index("ix_wc_card_match_id", "wc_card", ["match_id"])
    op.create_index("ix_wc_card_message_id", "wc_card", ["message_id"])


def downgrade() -> None:
    op.drop_index("ix_wc_card_message_id", table_name="wc_card")
    op.drop_index("ix_wc_card_match_id", table_name="wc_card")
    op.drop_index("ix_wc_card_guild_id", table_name="wc_card")
    op.drop_table("wc_card")
```

- [ ] **Step 7: Run tests + apply the migration**

```bash
.venv/bin/pytest tests/unit/test_wc_card_repo.py -q          # PASS
docker compose exec -T api alembic upgrade head
docker compose exec -T db psql -U postgres -d rolt9 -c "\dt wc_card"
```

- [ ] **Step 8: Lint + commit**

```bash
.venv/bin/ruff format app/models/wc_card.py app/repositories/wc_card.py app/db/base.py alembic/versions/*wc_card.py tests/unit/test_wc_card_repo.py
.venv/bin/ruff check app/models/wc_card.py app/repositories/wc_card.py
git add app/models/wc_card.py app/repositories/wc_card.py app/db/base.py alembic/versions/*wc_card.py tests/unit/test_wc_card_repo.py
git commit -F - <<'EOF'
feat(wc): wc_card table + repo (track posted cards, map reactions)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

### Task 4: Sync service — `sync_matches` + `settle_finished`

Pure-DB orchestration (no Discord) for unit-testing: pull matches from the API → upsert; score
finished matches.

**Files:** Create `app/services/wc/sync_service.py`; Test `tests/unit/test_wc_sync_service.py`.

- [ ] **Step 1: Write a failing test** `tests/unit/test_wc_sync_service.py`:

```python
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models.guild import Guild
from app.repositories.wc_prediction import WCPredictionRepository
from app.services.wc import sync_service
from app.services.wc.sync_service import settle_finished, sync_matches


@pytest.mark.asyncio
async def test_sync_matches_upserts(db_session, monkeypatch):
    async def fake_fetch():
        return [
            {"id": 10, "home_team": "BRA", "away_team": "ARG",
             "kickoff_at": datetime(2026, 6, 20, tzinfo=UTC), "status": "scheduled"},
        ]

    monkeypatch.setattr(sync_service, "fetch_wc_matches", fake_fetch)
    n = await sync_matches(db_session)
    await db_session.commit()
    assert n == 1


@pytest.mark.asyncio
async def test_settle_finished_scores_predictions(db_session, monkeypatch):
    # 1 guild, 1 finished match 2-1, 2 predictions: 1x2 home (correct=1pt), cs 0-0 (wrong=0pt)
    gid = uuid.uuid4()
    db_session.add(Guild(id=gid, discord_id=1, name="g", icon_url=None, is_active=True))

    async def fake_fetch():
        return [{"id": 20, "home_team": "BRA", "away_team": "ARG",
                 "kickoff_at": datetime.now(UTC) - timedelta(hours=3), "status": "finished",
                 "home_score": 2, "away_score": 1, "ou_line": 2.5}]

    monkeypatch.setattr(sync_service, "fetch_wc_matches", fake_fetch)
    await sync_matches(db_session)
    prepo = WCPredictionRepository(db_session)
    await prepo.upsert(gid, 20, 42, "1x2", "home")
    await prepo.upsert(gid, 20, 43, "cs", "0-0")
    await db_session.commit()

    settled = await settle_finished(db_session)
    await db_session.commit()
    assert settled == 1
    preds = await prepo.for_match(20)
    by_user = {p.user_discord_id: p.points for p in preds}
    assert by_user[42] == 1 and by_user[43] == 0
```

- [ ] **Step 2: Run it red** → FAIL.

- [ ] **Step 3: Write `app/services/wc/sync_service.py`**:

```python
"""Pure-DB WC orchestration (no Discord): sync matches + score finished matches.

Split out of the cog for unit-testing. The `wc_sync` cog just calls these 2 functions inside a
session_scope, then handles the Discord card posting/editing.
"""
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.wc_match import WCMatchRepository
from app.repositories.wc_prediction import WCPredictionRepository
from app.services.wc.football_api import fetch_wc_matches
from app.services.wc.scoring import score

log = logging.getLogger(__name__)


async def sync_matches(session: AsyncSession) -> int:
    """Pull all WC matches from the API, upsert into wc_match. Return the number processed."""
    matches = await fetch_wc_matches()
    repo = WCMatchRepository(session)
    for data in matches:
        await repo.upsert(data)
    if matches:
        log.info("wc sync: upserted %d matches", len(matches))
    return len(matches)


async def settle_finished(session: AsyncSession) -> int:
    """Score every finished, unsettled match: compute points per prediction (all guilds) -> set_points.

    Return the number scored. Matches with no score yet (home/away_score None) -> skipped, for a later tick.
    """
    mrepo = WCMatchRepository(session)
    prepo = WCPredictionRepository(session)
    count = 0
    for match in await mrepo.finished_unsettled():
        if match.home_score is None or match.away_score is None:
            continue  # finished but the API hasn't filled in the score -> wait for a later tick
        for pred in await prepo.for_match(match.id):
            pts = score(
                pred.bet_type, pred.pick,
                home_score=match.home_score, away_score=match.away_score,
                ou_line=match.ou_line, handicap_team=match.handicap_team,
                handicap_line=match.handicap_line,
            )
            await prepo.set_points(pred.id, pts)
        await mrepo.mark_settled(match.id)
        count += 1
    if count:
        log.info("wc settle: scored %d finished matches", count)
    return count
```

- [ ] **Step 4: Run it green** → PASS.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff format app/services/wc/sync_service.py tests/unit/test_wc_sync_service.py
.venv/bin/ruff check app/services/wc/sync_service.py
git add app/services/wc/sync_service.py tests/unit/test_wc_sync_service.py
git commit -F - <<'EOF'
feat(wc): sync service (upsert matches + settle finished -> score)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

### Task 5: Cog `wc_predict` — button View + score Modal + reactions + write/edit bets + `/wc-setup`

**Discord glue — verified manually.** Persistent view via `discord.ui.DynamicItem` (custom_id encodes
`wc:{bet}:{pick}:{match_id}`) so buttons survive restarts. A modal to enter the score. Flag reactions =
quick 1X2.

**Files:** Create `app/bot/cogs/wc_predict.py`; Test (smoke) `tests/unit/test_wc_predict_helpers.py`.

- [ ] **Step 1: Write pure helpers + tests** — pull parse/validate out for testing, leave the Discord part as glue.

`tests/unit/test_wc_predict_helpers.py`:
```python
import pytest

from app.bot.cogs.wc_predict import parse_score, build_custom_id, parse_custom_id


def test_parse_score_ok():
    assert parse_score("2-1") == (2, 1)
    assert parse_score(" 3 : 0 ") == (3, 0)


@pytest.mark.parametrize("bad", ["", "x", "2", "2-", "-1", "12", "a-b"])
def test_parse_score_bad(bad):
    assert parse_score(bad) is None


def test_custom_id_roundtrip():
    cid = build_custom_id("1x2", "home", 1001)
    assert parse_custom_id(cid) == ("1x2", "home", 1001)
```

- [ ] **Step 2: Run it red** → FAIL.

- [ ] **Step 3: Write `app/bot/cogs/wc_predict.py`.** A full skeleton (following the `agent.py` View +
  `session_scope` + slash command admin check pattern). Key points:
  - `parse_score`, `build_custom_id`, `parse_custom_id` (pure functions, tested).
  - `WCButton(discord.ui.DynamicItem[...])` with a `template` regex parsing `bet/pick/match`; the callback
    writes/edits the prediction (cs → opens a Modal), checks the lock at kickoff.
  - `WCScoreModal(discord.ui.Modal)` to enter the score → upsert cs.
  - `WCPredictCog`: listener `on_raw_reaction_add` / `on_raw_reaction_remove` (home/away flag →
    upsert/cancel 1x2); command group `app_commands.Group("wc", guild_only=True)` containing `setup`.

```python
"""WC Predict cog — buttons/modal/reactions for players to predict + /wc-setup (admin).

Buttons use DynamicItem (persistent) so they survive restarts: custom_id = 'wc:{bet}:{pick}:{match_id}'.
Every bet write checks the lock at kickoff (compares match.kickoff_at to now). Error -> ephemeral reply.
"""
import logging
import re
import uuid
from datetime import UTC, datetime

import discord
from discord import app_commands
from discord.ext import commands

from app.db.session import session_scope
from app.discord_io.client import DiscordClient
from app.repositories.guild import GuildRepository
from app.repositories.wc_card import WCCardRepository
from app.repositories.wc_config import WCConfigRepository
from app.repositories.wc_match import WCMatchRepository
from app.repositories.wc_prediction import WCPredictionRepository
from app.services.wc.cards import is_locked

log = logging.getLogger(__name__)

_PICK_LABEL = {  # to report back to the player
    "home": "home", "draw": "draw", "away": "away",
    "over": "Over", "under": "Under", "favorite": "favorite", "underdog": "underdog",
}


def parse_score(raw: str) -> tuple[int, int] | None:
    """'2-1' / '3:0' -> (2, 1). Bad format -> None. Only accepts 0-99 per side."""
    if not raw:
        return None
    m = re.fullmatch(r"\s*(\d{1,2})\s*[-:]\s*(\d{1,2})\s*", raw)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def build_custom_id(bet: str, pick: str, match_id: int) -> str:
    return f"wc:{bet}:{pick}:{match_id}"


def parse_custom_id(cid: str) -> tuple[str, str, int] | None:
    m = re.fullmatch(r"wc:([a-z0-9]+):([a-z_]+):(\d+)", cid)
    if not m:
        return None
    return m.group(1), m.group(2), int(m.group(3))


async def _record_prediction(session, *, guild_discord_id: int, match_id: int, user_id: int,
                             bet: str, pick: str) -> str:
    """Write/edit one prediction after the lock check. Return the reply line (recorded / locked / error)."""
    guild = await GuildRepository(session).get_by_discord_id(guild_discord_id)
    if guild is None:
        return "❌ Server not initialized."
    match = await WCMatchRepository(session).get(match_id)
    if match is None:
        return "❌ Match not found."
    if is_locked(match, datetime.now(UTC)):
        return "🔒 Bets are locked (kickoff has started)."
    await WCPredictionRepository(session).upsert(guild.id, match_id, user_id, bet, pick)
    label = _PICK_LABEL.get(pick, pick)
    return f"✅ Recorded bet **{bet}**: {label}."


# ---- Score-entry modal ----
class WCScoreModal(discord.ui.Modal, title="🎯 Predict the exact score"):
    score_in = discord.ui.TextInput(label="Score (home-away)", placeholder="e.g. 2-1", max_length=5)

    def __init__(self, match_id: int):
        super().__init__()
        self.match_id = match_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        parsed = parse_score(str(self.score_in.value))
        if parsed is None:
            await interaction.response.send_message("❌ Invalid score (e.g. 2-1).", ephemeral=True)
            return
        pick = f"{parsed[0]}-{parsed[1]}"
        async with session_scope() as session:
            msg = await _record_prediction(
                session, guild_discord_id=interaction.guild_id, match_id=self.match_id,
                user_id=interaction.user.id, bet="cs", pick=pick,
            )
        await interaction.response.send_message(f"{msg} (score {pick})", ephemeral=True)


# ---- Persistent buttons (DynamicItem) ----
class WCButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"wc:(?P<bet>[a-z0-9]+):(?P<pick>[a-z_]+):(?P<match>\d+)",
):
    def __init__(self, bet: str, pick: str, match_id: int, *, label: str, style=discord.ButtonStyle.primary):
        self.bet, self.pick, self.match_id = bet, pick, match_id
        super().__init__(
            discord.ui.Button(label=label, style=style, custom_id=build_custom_id(bet, pick, match_id))
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        bet, pick, mid = match["bet"], match["pick"], int(match["match"])
        return cls(bet, pick, mid, label="…")

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.bet == "cs":  # open the score-entry modal
            await interaction.response.send_modal(WCScoreModal(self.match_id))
            return
        async with session_scope() as session:
            msg = await _record_prediction(
                session, guild_discord_id=interaction.guild_id, match_id=self.match_id,
                user_id=interaction.user.id, bet=self.bet, pick=self.pick,
            )
        await interaction.response.send_message(msg, ephemeral=True)


def build_card_view(match) -> discord.ui.View:
    """The View attached to a match card: 1X2 + Over/Under + Handicap + Predict score buttons. timeout=None (persistent)."""
    view = discord.ui.View(timeout=None)
    mid = match.id
    view.add_item(WCButton("1x2", "home", mid, label=match.home_team[:40]))
    view.add_item(WCButton("1x2", "draw", mid, label="Draw", style=discord.ButtonStyle.secondary))
    view.add_item(WCButton("1x2", "away", mid, label=match.away_team[:40]))
    view.add_item(WCButton("ou", "over", mid, label="Over", style=discord.ButtonStyle.success))
    view.add_item(WCButton("ou", "under", mid, label="Under", style=discord.ButtonStyle.success))
    view.add_item(WCButton("ah", "favorite", mid, label="Favorite", style=discord.ButtonStyle.secondary))
    view.add_item(WCButton("ah", "underdog", mid, label="Underdog", style=discord.ButtonStyle.secondary))
    view.add_item(WCButton("cs", "modal", mid, label="🎯 Predict score", style=discord.ButtonStyle.danger))
    return view


class WCPredictCog(commands.Cog):
    def __init__(self, bot: commands.Bot, discord_io: DiscordClient):
        self.bot = bot
        self.discord_io = discord_io

    # ---- Reaction quick-1X2 ----
    async def _flag_pick(self, session, card, emoji: str) -> str | None:
        """The card's home/away flag -> 'home'/'away'. No match -> None."""
        from app.services.wc.flags import flag
        match = await WCMatchRepository(session).get(card.match_id)
        if match is None:
            return None
        if emoji == flag(match.home_code):
            return "home"
        if emoji == flag(match.away_code):
            return "away"
        return None

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.user_id == self.bot.user.id or payload.guild_id is None:
            return
        async with session_scope() as session:
            card = await WCCardRepository(session).by_message(payload.message_id)
            if card is None:
                return
            pick = await self._flag_pick(session, card, str(payload.emoji))
            if pick is None:
                return
            await _record_prediction(
                session, guild_discord_id=payload.guild_id, match_id=card.match_id,
                user_id=payload.user_id, bet="1x2", pick=pick,
            )

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.guild_id is None:
            return
        async with session_scope() as session:
            card = await WCCardRepository(session).by_message(payload.message_id)
            if card is None:
                return
            match = await WCMatchRepository(session).get(card.match_id)
            if match is None or is_locked(match, datetime.now(UTC)):
                return
            pick = await self._flag_pick(session, card, str(payload.emoji))
            if pick is None:
                return
            # Removing the flag -> cancel the 1x2 prediction if it currently matches that pick
            guild = await GuildRepository(session).get_by_discord_id(payload.guild_id)
            if guild is None:
                return
            prepo = WCPredictionRepository(session)
            mine = await prepo.for_user_match(guild.id, card.match_id, payload.user_id)
            for p in mine:
                if p.bet_type == "1x2" and p.pick == pick:
                    await session.delete(p)
            await session.flush()

    # ---- /wc-setup ----
    wc = app_commands.Group(name="wc", description="World Cup predictions", guild_only=True)

    @wc.command(name="setup", description="Enable/configure WC Predict (needs Manage Server).")
    @app_commands.describe(channel="Channel to post match cards", enabled="On/off", shame_prefix="Shaming nick prefix")
    async def wc_setup(self, interaction: discord.Interaction,
                       channel: discord.TextChannel | None = None,
                       enabled: bool | None = None,
                       shame_prefix: str | None = None) -> None:
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Needs **Manage Server** permission.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        data: dict = {}
        if channel is not None:
            data["channel_id"] = channel.id
        if enabled is not None:
            data["enabled"] = enabled
        if shame_prefix is not None:
            data["shame_nick_prefix"] = shame_prefix[:40]
        async with session_scope() as session:
            guild = await GuildRepository(session).get_by_discord_id(interaction.guild_id)
            if guild is None:
                await interaction.followup.send("❌ Server not initialized.", ephemeral=True)
                return
            cfg = await WCConfigRepository(session).upsert(guild.id, data)
            ch = f"<#{cfg.channel_id}>" if cfg.channel_id else "(not set)"
            state = "ON ✅" if cfg.enabled else "OFF ⛔"
        await interaction.followup.send(
            f"⚙️ WC Predict: {state} • channel {ch} • shaming nick prefix `{cfg.shame_nick_prefix}`",
            ephemeral=True,
        )
```

- [ ] **Step 4: Run the helper tests** → PASS (`.venv/bin/pytest tests/unit/test_wc_predict_helpers.py -q`).

- [ ] **Step 5: Lint + commit** (cog not registered yet — done in Task 7)

```bash
.venv/bin/ruff format app/bot/cogs/wc_predict.py tests/unit/test_wc_predict_helpers.py
.venv/bin/ruff check app/bot/cogs/wc_predict.py
git add app/bot/cogs/wc_predict.py tests/unit/test_wc_predict_helpers.py
git commit -F - <<'EOF'
feat(wc): predict cog (persistent buttons, score modal, flag reactions, /wc-setup)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

### Task 6: Cog `wc_sync` — loop sync → post cards → settle

**Glue — verified manually.** A 2–5 minute tick: (1) `sync_matches`; (2) for each enabled guild, post
cards for upcoming matches (within the pre-kickoff window, not yet posted) + pre-add the 2 flags; (3)
`settle_finished`; (4) lock cards at kickoff (edit the footer + remove the view).

**Files:** Create `app/bot/cogs/wc_sync.py`.

- [ ] **Step 1: Write `app/bot/cogs/wc_sync.py`** (following `subscription.py`/`companion.py`):

```python
"""WC Sync cog — loop: sync matches from the API, post upcoming match cards, score finished matches, lock cards.

Pattern follows SubscriptionCog: session_scope per tick, one failing tick doesn't kill the loop. Only
posts cards for guilds that have run /wc-setup (enabled + channel_id). Uses wc_card to prevent re-posting.
"""
import logging
from datetime import UTC, datetime, timedelta

import discord
from discord.ext import commands, tasks

from app.db.session import session_scope
from app.discord_io.client import DiscordClient
from app.repositories.wc_card import WCCardRepository
from app.repositories.wc_config import WCConfigRepository
from app.repositories.wc_match import WCMatchRepository
from app.services.wc.cards import build_match_embed, flag_pair := None  # see note below
from app.services.wc.flags import flag
from app.services.wc.sync_service import settle_finished, sync_matches
from app.bot.cogs.wc_predict import build_card_view

log = logging.getLogger(__name__)

SYNC_MINUTES = 3
POST_WINDOW_HOURS = 12  # post a card when the match is <= 12h to kickoff


class WCSyncCog(commands.Cog):
    def __init__(self, bot: commands.Bot, discord_io: DiscordClient):
        self.bot = bot
        self.discord_io = discord_io

    async def cog_load(self) -> None:
        self.wc_tick.start()

    def cog_unload(self) -> None:
        self.wc_tick.cancel()

    @tasks.loop(minutes=SYNC_MINUTES)
    async def wc_tick(self) -> None:
        try:
            async with session_scope() as session:
                await sync_matches(session)
                await settle_finished(session)
            await self._post_due_cards()
        except Exception:  # noqa: BLE001
            log.exception("wc sync: tick failed")

    @wc_tick.before_loop
    async def _before(self) -> None:
        await self.bot.wait_until_ready()

    async def _post_due_cards(self) -> None:
        now = datetime.now(UTC)
        horizon = now + timedelta(hours=POST_WINDOW_HOURS)
        async with session_scope() as session:
            configs = await WCConfigRepository(session).all_enabled()  # enabled + channel_id != None
            mrepo = WCMatchRepository(session)
            crepo = WCCardRepository(session)
            # scheduled matches in the window (note: finished_unsettled doesn't fit; we need a separate query)
            upcoming = await mrepo.upcoming(now, horizon)  # ADD this method, see note
            for cfg in configs:
                channel = self.bot.get_channel(cfg.channel_id)
                if channel is None:
                    continue
                for match in upcoming:
                    if await crepo.exists(cfg.guild_id, match.id):
                        continue
                    try:
                        msg = await channel.send(
                            embed=build_match_embed(match, locked=False),
                            view=build_card_view(match),
                        )
                        await crepo.record(cfg.guild_id, match.id,
                                           channel_id=cfg.channel_id, message_id=msg.id)
                        # pre-add the 2 flags for quick prediction
                        for code in (match.home_code, match.away_code):
                            try:
                                await msg.add_reaction(flag(code))
                            except discord.DiscordException:
                                pass
                    except discord.DiscordException:
                        log.warning("wc: post card failed guild=%s match=%s", cfg.guild_id, match.id)
```

> **Notes when coding Task 6:**
> - Drop the `flag_pair := None` line (a bad placeholder import) — you only need `from app.services.wc.flags import flag`.
> - Add `WCMatchRepository.upcoming(self, start, end)` to `app/repositories/wc_match.py`:
>   ```python
>   async def upcoming(self, start, end) -> list[WCMatch]:
>       res = await self.session.execute(
>           select(WCMatch).where(
>               WCMatch.status == "scheduled",
>               WCMatch.kickoff_at >= start, WCMatch.kickoff_at <= end,
>           ).order_by(WCMatch.kickoff_at)
>       )
>       return list(res.scalars().all())
>   ```
>   (Add a small test in `tests/unit/test_wc_repos.py` for `upcoming`.)
> - **Lock cards at kickoff:** add a step in `_post_due_cards` or a separate method: for each
>   `crepo.unlocked_cards()` whose `match.kickoff_at <= now` → fetch the message
>   (`channel.fetch_message(card.message_id)`), `await msg.edit(embed=build_match_embed(match,
>   locked=True), view=None)`, `await crepo.mark_locked(card.guild_id, card.match_id)`.

- [ ] **Step 2: Add `upcoming` + test, run `.venv/bin/pytest -q`** (the suite must be green).

- [ ] **Step 3: Lint + commit**

```bash
.venv/bin/ruff format app/bot/cogs/wc_sync.py app/repositories/wc_match.py tests/unit/test_wc_repos.py
.venv/bin/ruff check app/bot/cogs/wc_sync.py app/repositories/wc_match.py
git add app/bot/cogs/wc_sync.py app/repositories/wc_match.py tests/unit/test_wc_repos.py
git commit -F - <<'EOF'
feat(wc): sync cog (loop: sync API, post match cards, settle, lock)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

### Task 7: Register the cogs + persistent items in `client.py`

**Files:** Modify `app/bot/client.py`.

- [ ] **Step 1: Edit `setup_hook`** in `app/bot/client.py` — add the imports + register the 2 cogs +
  register the DynamicItem so persistent buttons work after a restart. Add near the other `add_cog` calls:

```python
from app.bot.cogs.wc_predict import WCButton, WCPredictCog
from app.bot.cogs.wc_sync import WCSyncCog
# ... in setup_hook, before self.tree.sync():
self.add_dynamic_items(WCButton)
await self.add_cog(WCPredictCog(self, self.discord_io))
await self.add_cog(WCSyncCog(self, self.discord_io))
```

> `add_dynamic_items` registers the dynamic button class so Discord re-routes clicks after a restart (discord.py 2.4).
> If your discord.py version lacks `add_dynamic_items`, use `self.add_view` with a persistent view +
> `WCButton.from_custom_id` — check `discord.__version__` when coding.

- [ ] **Step 2: Start the bot, `docker compose logs -f api`** and confirm: "Cogs loaded", no import
  errors, the `wc_tick` loop runs.

- [ ] **Step 3: Commit**

```bash
git add app/bot/client.py
git commit -F - <<'EOF'
feat(wc): register wc_predict + wc_sync cogs + persistent buttons

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

## Manual verification checklist (on a real server)

Needs `FOOTBALL_DATA_API_KEY` in the env + an upcoming WC match (or temporarily seed one scheduled
`wc_match` in the DB to test cards).

- [ ] `/wc-setup channel:#bets enabled:true` → reports ON + the correct channel.
- [ ] Within ≤ `SYNC_MINUTES`+`POST_WINDOW`, a match card appears in the channel: the title has **both
  teams' flags**, the Vietnam time is correct (UTC+7), the 1X2/Over-Under/Favorite-Underdog/🎯 buttons,
  and the bot has pre-added the 2 flags.
- [ ] Click a 1X2 button → ephemeral "✅ Recorded bet". Click a different pick → it updates (no duplicate
  — check the DB `wc_prediction` has only 1 row/bet_type).
- [ ] Click 🎯 → modal appears → enter `2-1` → "✅ ... (score 2-1)". Enter `abc` → "❌ invalid".
- [ ] React with the home flag → creates a 1x2 home prediction (check the DB). Remove the flag → deletes that prediction.
- [ ] After kickoff: click a button → "🔒 Bets are locked". The card is edited with footer "🔒 Locked" + loses its buttons.
- [ ] When a match is `finished` with a score: within ≤ `SYNC_MINUTES`, `wc_prediction.points` is filled
  correctly (matching `scoring.score`), `wc_match.settled=true`, and it's not re-scored on later ticks.
- [ ] **Restart the bot** → clicking a button on an old card still works (persistent view OK).
- [ ] `/wc-setup enabled:false` → stops posting new cards.

## Self-review (sweep before handing off)

- **Phase 2 spec coverage:** sync loop ✅; post cards with flags+buttons ✅; score modal ✅; flag
  quick-1X2 ✅; lock at kickoff ✅; auto-settle ✅; `/wc-setup` (enable/channel/prefix) ✅.
  (Leaderboard/punishment/AI = Phase 3-4.)
- **Type consistency:** `pick` values match `_PICK_LABEL` + `scoring.score`; `build_custom_id`/
  `parse_custom_id`/`WCButton.template` use the same `wc:bet:pick:match` format; `WCMatchRepository.upcoming`
  returns `list[WCMatch]` matching `_post_due_cards`.
- **Edge:** a finished match with no score yet → settle skips it; a deleted channel → `get_channel` None → skip;
  an already-posted card → `crepo.exists` blocks the duplicate.
