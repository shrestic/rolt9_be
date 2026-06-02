# WC Predict — Pha 2: Sync loop + Thẻ trận + /wc-setup (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (hoặc
> executing-plans) để chạy plan này task-by-task. Bước có checkbox `- [ ]`.

**Goal:** Bot tự kéo lịch World Cup theo nhịp, đăng thẻ trận có cờ + nút bấm + modal tỉ số + thả-cờ
đoán nhanh vào kênh từng server bật, ghi/sửa dự đoán tới lúc bóng lăn, và tự chấm điểm khi trận
kết thúc. Admin bật/cấu hình bằng `/wc-setup`.

**Architecture:** Tách **logic thuần/service** (flags, render thẻ, sync+settle) ra để unit-test;
phần **Discord glue** (cog loop, View/Modal/reaction, slash command) verify thủ công. Thẻ trận dùng
**persistent view** (`discord.ui.DynamicItem`, discord.py 2.4) để nút sống qua restart; `custom_id`
mã hoá `bet_type:pick:match_id`. Thêm bảng `wc_card` để biết thẻ nào đã đăng (chống đăng lại) + map
message ↔ trận cho reaction.

**Tech Stack:** discord.py 2.4 (`tasks.loop`, `app_commands`, `ui.View/Modal/DynamicItem`,
`on_raw_reaction_add/remove`), SQLAlchemy 2 async, Alembic, pytest. Foundation Pha 1 đã có.

**Phụ thuộc Pha 1:** `app.services.wc.scoring.score/POINTS`, `app.services.wc.football_api.fetch_wc_matches`,
`WCMatchRepository`, `WCPredictionRepository`, `WCConfigRepository`, models `WCMatch/WCPrediction/GuildWCConfig`.

---

## File structure

| File | Trách nhiệm | Test? |
|---|---|---|
| `app/services/wc/flags.py` | Mã đội (tla/code) → emoji cờ | ✅ unit |
| `app/services/wc/cards.py` | Render Embed thẻ trận + helper giờ-VN / nhãn kèo / khoá | ✅ unit (phần thuần) |
| `app/models/wc_card.py` | Bảng `wc_card`: thẻ đã đăng (guild,match,channel,message) | — |
| `app/repositories/wc_card.py` | Data access `wc_card` | ✅ unit |
| `alembic/versions/<ts>_wc_card.py` | Migration bảng `wc_card` | — |
| `app/services/wc/sync_service.py` | `sync_matches` + `settle_finished` (orchestration thuần-DB) | ✅ unit |
| `app/bot/cogs/wc_predict.py` | View nút + Modal tỉ số + reaction quick-1X2 + ghi/sửa kèo + `/wc-setup` | manual |
| `app/bot/cogs/wc_sync.py` | `tasks.loop`: sync → đăng thẻ → settle | manual |
| `app/bot/client.py` | Đăng ký 2 cog + persistent dynamic items (sửa `setup_hook`) | manual |

**Quy ước `pick`:** `1x2` → `home|draw|away`; `ou` → `over|under` (mốc = `match.ou_line`);
`ah` → `favorite|underdog` (đội/mốc = `match.handicap_team`/`handicap_line`); `cs` → chuỗi `"H-A"`.

---

### Task 1: Flags — mã đội → emoji cờ

**Files:** Create `app/services/wc/flags.py`; Test `tests/unit/test_wc_flags.py`.

football-data.org trả `tla` (mã FIFA 3 ký tự, vd `BRA`). Emoji cờ Unicode cần mã ISO-2
(`BR`→🇧🇷). Ta map FIFA→cờ bằng dict cho các nước WC; thiếu → 🏳️.

- [ ] **Step 1: Viết test thất bại** `tests/unit/test_wc_flags.py`:

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

- [ ] **Step 2: Chạy cho thất bại** — `.venv/bin/pytest tests/unit/test_wc_flags.py -q` → FAIL (ModuleNotFound).

- [ ] **Step 3: Viết `app/services/wc/flags.py`** (ISO-2 → cờ bằng regional indicators; map FIFA→ISO2):

```python
"""Mã đội (FIFA tla, vd 'BRA') -> emoji cờ. Thiếu mã -> cờ trắng 🏳️.

football-data.org trả tla 3 ký tự; emoji cờ cần ISO-3166 alpha-2. Dict dưới phủ các đội WC
phổ biến; bổ sung khi cần. flag() chịu được None/mã lạ (trả 🏳️) để không bao giờ làm vỡ thẻ.
"""

# FIFA tla -> ISO-2. Bổ sung dần khi gặp đội mới.
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
    """Trả emoji cờ cho mã đội (FIFA tla hoặc ISO-2). Không khớp -> 🏳️."""
    if not code:
        return "🏳️"
    c = code.strip().upper()
    iso2 = _FIFA_TO_ISO2.get(c, c if len(c) == 2 else "")
    if len(iso2) != 2 or not iso2.isalpha():
        return "🏳️"
    # Ghép 2 regional indicator: 'A' (0x41) -> 0x1F1E6
    return "".join(chr(0x1F1E6 + (ord(ch) - ord("A"))) for ch in iso2)
```

- [ ] **Step 4: Chạy cho pass** — `.venv/bin/pytest tests/unit/test_wc_flags.py -q` → PASS.

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

### Task 2: Cards — render thẻ trận + helper

**Files:** Create `app/services/wc/cards.py`; Test `tests/unit/test_wc_cards.py`.

- [ ] **Step 1: Viết test thất bại** `tests/unit/test_wc_cards.py`:

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
    # 12:00 UTC -> 19:00 giờ VN
    assert "19:00" in vn_time(datetime(2026, 6, 20, 12, 0, tzinfo=UTC))


def test_is_locked_at_kickoff():
    m = _m()
    assert is_locked(m, m.kickoff_at - timedelta(minutes=1)) is False
    assert is_locked(m, m.kickoff_at) is True
    assert is_locked(m, m.kickoff_at + timedelta(minutes=1)) is True


def test_ou_label_shows_line():
    assert "2.5" in ou_label(_m())


def test_handicap_label_names_favorite():
    # home chấp 1.0 -> Brazil là cửa trên
    assert "Brazil" in handicap_label(_m())
    assert "1" in handicap_label(_m())
```

- [ ] **Step 2: Chạy cho thất bại** → FAIL.

- [ ] **Step 3: Viết `app/services/wc/cards.py`** (helper thuần + builder Embed):

```python
"""Render thẻ trận WC (Embed) + helper thuần (giờ VN, nhãn kèo, khoá tại kickoff).

Phần thuần (vn_time/is_locked/ou_label/handicap_label) tách riêng để unit-test; build_match_embed
ghép chúng thành discord.Embed. KHÔNG gọi I/O.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

import discord

from app.models.wc_match import WCMatch
from app.services.wc.flags import flag

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def vn_time(dt: datetime) -> str:
    """Giờ kickoff theo VN, vd '19:00 20/06'."""
    return dt.astimezone(VN_TZ).strftime("%H:%M %d/%m")


def is_locked(match: WCMatch, now: datetime) -> bool:
    """Khoá kèo khi đã tới/qua giờ bóng lăn."""
    return now >= match.kickoff_at


def ou_label(match: WCMatch) -> str:
    return f"Tài/Xỉu {match.ou_line:g}"


def handicap_label(match: WCMatch) -> str:
    """Nhãn kèo chấp, vd 'Brazil chấp 1' (đội cửa trên + mốc)."""
    if match.handicap_team not in ("home", "away") or match.handicap_line is None:
        return "Kèo chấp (chưa có)"
    fav = match.home_team if match.handicap_team == "home" else match.away_team
    return f"{fav} chấp {match.handicap_line:g}"


def title(match: WCMatch) -> str:
    return f"{flag(match.home_code)} {match.home_team}  vs  {match.away_team} {flag(match.away_code)}"


def build_match_embed(match: WCMatch, *, locked: bool, hot_take: str | None = None) -> discord.Embed:
    """Embed thẻ trận: tiêu đề có cờ, giờ VN, các kèo, trạng thái khoá. hot_take (Pha 4) tùy chọn."""
    desc_lines = [f"🕐 **{vn_time(match.kickoff_at)}** (giờ VN)"]
    if match.stage:
        desc_lines.append(f"🏟️ {match.stage}")
    if hot_take:
        desc_lines.append(f"\n💬 *{hot_take}*")
    embed = discord.Embed(title=title(match), description="\n".join(desc_lines), color=0x1FAA59)
    embed.add_field(name="1X2", value=f"{match.home_team} / Hòa / {match.away_team}", inline=False)
    embed.add_field(name="Tài/Xỉu", value=ou_label(match), inline=True)
    embed.add_field(name="Chấp", value=handicap_label(match), inline=True)
    embed.set_footer(
        text="🔒 Đã khoá kèo" if locked else "Bấm nút để đoán • thả cờ = đoán nhanh 1X2 • khoá khi bóng lăn"
    )
    return embed
```

- [ ] **Step 4: Chạy cho pass** → PASS.

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

### Task 3: Bảng `wc_card` + repo + migration

Theo dõi thẻ đã đăng theo (guild, match) để (a) không đăng lại, (b) map message_id → trận cho
reaction, (c) cập nhật/khoá thẻ khi tới giờ.

**Files:** Create `app/models/wc_card.py`, `app/repositories/wc_card.py`,
`alembic/versions/<timestamp>_wc_card.py`; Modify `app/db/base.py`; Test `tests/unit/test_wc_card_repo.py`.

- [ ] **Step 1: Viết test thất bại** `tests/unit/test_wc_card_repo.py`:

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
    assert await repo.mark_locked(gid, 7) is None  # không lỗi khi gọi
    await db_session.commit()
```

- [ ] **Step 2: Chạy cho thất bại** → FAIL.

- [ ] **Step 3: Model `app/models/wc_card.py`**:

```python
"""Bảng `wc_card` — thẻ trận đã đăng cho 1 (guild, match): để chống đăng lại + map reaction."""
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
"""Data access cho wc_card (thẻ trận đã đăng per guild/match)."""
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

- [ ] **Step 5: Đăng ký trong `app/db/base.py`** — thêm dòng (giữ thứ tự alphabet với các import wc):

```python
from app.models.wc_card import WCCard  # noqa: F401
```

- [ ] **Step 6: Migration** — `down_revision` = head HIỆN TẠI (chạy `docker compose exec -T api alembic heads`
  để lấy; lúc viết plan head Pha 1 là `c0ffee0wc001`, NHƯNG verify lại). File
  `alembic/versions/<timestamp>_wc_card.py`:

```python
"""WC Predict Pha 2: bảng wc_card

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

- [ ] **Step 7: Chạy test + apply migration**

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

Orchestration thuần-DB (không Discord) để unit-test: kéo trận từ API → upsert; chấm trận đã xong.

**Files:** Create `app/services/wc/sync_service.py`; Test `tests/unit/test_wc_sync_service.py`.

- [ ] **Step 1: Viết test thất bại** `tests/unit/test_wc_sync_service.py`:

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
    # 1 guild, 1 trận finished 2-1, 2 dự đoán: 1x2 home (đúng=1đ), cs 0-0 (sai=0đ)
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

- [ ] **Step 2: Chạy cho thất bại** → FAIL.

- [ ] **Step 3: Viết `app/services/wc/sync_service.py`**:

```python
"""Orchestration WC thuần-DB (không Discord): đồng bộ trận + chấm điểm trận đã xong.

Tách khỏi cog để unit-test. Cog `wc_sync` chỉ gọi 2 hàm này trong session_scope rồi lo phần
đăng/sửa thẻ Discord.
"""
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.wc_match import WCMatchRepository
from app.repositories.wc_prediction import WCPredictionRepository
from app.services.wc.football_api import fetch_wc_matches
from app.services.wc.scoring import score

log = logging.getLogger(__name__)


async def sync_matches(session: AsyncSession) -> int:
    """Kéo toàn bộ trận WC từ API, upsert vào wc_match. Trả số trận đã xử lý."""
    matches = await fetch_wc_matches()
    repo = WCMatchRepository(session)
    for data in matches:
        await repo.upsert(data)
    if matches:
        log.info("wc sync: upserted %d matches", len(matches))
    return len(matches)


async def settle_finished(session: AsyncSession) -> int:
    """Chấm mọi trận finished chưa settled: tính điểm từng prediction (mọi guild) -> set_points.

    Trả số trận đã chấm. Trận chưa có tỉ số (home/away_score None) -> bỏ qua, để nhịp sau.
    """
    mrepo = WCMatchRepository(session)
    prepo = WCPredictionRepository(session)
    count = 0
    for match in await mrepo.finished_unsettled():
        if match.home_score is None or match.away_score is None:
            continue  # finished nhưng API chưa kịp tỉ số -> chờ nhịp sau
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

- [ ] **Step 4: Chạy cho pass** → PASS.

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

### Task 5: Cog `wc_predict` — View nút + Modal tỉ số + reaction + ghi/sửa kèo + `/wc-setup`

**Glue Discord — verify thủ công.** Persistent view qua `discord.ui.DynamicItem` (custom_id mã hoá
`wc:{bet}:{pick}:{match_id}`) để nút sống sau restart. Modal nhập tỉ số. Reaction cờ = đoán nhanh 1X2.

**Files:** Create `app/bot/cogs/wc_predict.py`; Test (smoke) `tests/unit/test_wc_predict_helpers.py`.

- [ ] **Step 1: Viết helper thuần + test** — tách parse/validate ra để test, phần Discord để glue.

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

- [ ] **Step 2: Chạy cho thất bại** → FAIL.

- [ ] **Step 3: Viết `app/bot/cogs/wc_predict.py`.** Khung đầy đủ (bám pattern `agent.py` View +
  `session_scope` + slash command admin check). Điểm chính:
  - `parse_score`, `build_custom_id`, `parse_custom_id` (hàm thuần, có test).
  - `WCButton(discord.ui.DynamicItem[...])` với `template` regex parse `bet/pick/match`; callback
    ghi/sửa prediction (cs → mở Modal), check khoá tại kickoff.
  - `WCScoreModal(discord.ui.Modal)` nhập tỉ số → upsert cs.
  - `WCPredictCog`: listener `on_raw_reaction_add` / `on_raw_reaction_remove` (cờ home/away →
    upsert/huỷ 1x2); nhóm lệnh `app_commands.Group("wc", guild_only=True)` chứa `setup`.

```python
"""Cog WC Predict — nút/modal/reaction để người chơi đoán + /wc-setup (admin).

Nút dùng DynamicItem (persistent) nên sống qua restart: custom_id = 'wc:{bet}:{pick}:{match_id}'.
Mọi ghi kèo đều check khoá tại kickoff (so match.kickoff_at với now). Lỗi -> phản hồi ephemeral.
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

_PICK_LABEL = {  # để báo lại cho người chơi
    "home": "đội nhà", "draw": "hòa", "away": "đội khách",
    "over": "Tài", "under": "Xỉu", "favorite": "cửa trên", "underdog": "cửa dưới",
}


def parse_score(raw: str) -> tuple[int, int] | None:
    """'2-1' / '3:0' -> (2, 1). Sai định dạng -> None. Chỉ nhận 0-99 mỗi vế."""
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
    """Ghi/sửa 1 prediction sau khi check khoá. Trả câu phản hồi (đã đoán / đã khoá / lỗi)."""
    guild = await GuildRepository(session).get_by_discord_id(guild_discord_id)
    if guild is None:
        return "❌ Server chưa khởi tạo."
    match = await WCMatchRepository(session).get(match_id)
    if match is None:
        return "❌ Không tìm thấy trận."
    if is_locked(match, datetime.now(UTC)):
        return "🔒 Trận đã khoá kèo (bóng lăn rồi)."
    await WCPredictionRepository(session).upsert(guild.id, match_id, user_id, bet, pick)
    label = _PICK_LABEL.get(pick, pick)
    return f"✅ Đã ghi kèo **{bet}**: {label}."


# ---- Modal nhập tỉ số ----
class WCScoreModal(discord.ui.Modal, title="🎯 Đoán tỉ số chính xác"):
    score_in = discord.ui.TextInput(label="Tỉ số (nhà-khách)", placeholder="vd 2-1", max_length=5)

    def __init__(self, match_id: int):
        super().__init__()
        self.match_id = match_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        parsed = parse_score(str(self.score_in.value))
        if parsed is None:
            await interaction.response.send_message("❌ Tỉ số không hợp lệ (vd 2-1).", ephemeral=True)
            return
        pick = f"{parsed[0]}-{parsed[1]}"
        async with session_scope() as session:
            msg = await _record_prediction(
                session, guild_discord_id=interaction.guild_id, match_id=self.match_id,
                user_id=interaction.user.id, bet="cs", pick=pick,
            )
        await interaction.response.send_message(f"{msg} (tỉ số {pick})", ephemeral=True)


# ---- Nút persistent (DynamicItem) ----
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
        if self.bet == "cs":  # mở modal nhập tỉ số
            await interaction.response.send_modal(WCScoreModal(self.match_id))
            return
        async with session_scope() as session:
            msg = await _record_prediction(
                session, guild_discord_id=interaction.guild_id, match_id=self.match_id,
                user_id=interaction.user.id, bet=self.bet, pick=self.pick,
            )
        await interaction.response.send_message(msg, ephemeral=True)


def build_card_view(match) -> discord.ui.View:
    """View gắn vào thẻ trận: nút 1X2 + Tài/Xỉu + Chấp + Đoán tỉ số. timeout=None (persistent)."""
    view = discord.ui.View(timeout=None)
    mid = match.id
    view.add_item(WCButton("1x2", "home", mid, label=match.home_team[:40]))
    view.add_item(WCButton("1x2", "draw", mid, label="Hòa", style=discord.ButtonStyle.secondary))
    view.add_item(WCButton("1x2", "away", mid, label=match.away_team[:40]))
    view.add_item(WCButton("ou", "over", mid, label="Tài", style=discord.ButtonStyle.success))
    view.add_item(WCButton("ou", "under", mid, label="Xỉu", style=discord.ButtonStyle.success))
    view.add_item(WCButton("ah", "favorite", mid, label="Cửa trên", style=discord.ButtonStyle.secondary))
    view.add_item(WCButton("ah", "underdog", mid, label="Cửa dưới", style=discord.ButtonStyle.secondary))
    view.add_item(WCButton("cs", "modal", mid, label="🎯 Đoán tỉ số", style=discord.ButtonStyle.danger))
    return view


class WCPredictCog(commands.Cog):
    def __init__(self, bot: commands.Bot, discord_io: DiscordClient):
        self.bot = bot
        self.discord_io = discord_io

    # ---- Reaction quick-1X2 ----
    async def _flag_pick(self, session, card, emoji: str) -> str | None:
        """Cờ home/away của thẻ -> 'home'/'away'. Không khớp -> None."""
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
            # Gỡ cờ -> huỷ dự đoán 1x2 nếu đang đúng pick đó
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
    wc = app_commands.Group(name="wc", description="World Cup dự đoán", guild_only=True)

    @wc.command(name="setup", description="Bật/cấu hình WC Predict (cần Manage Server).")
    @app_commands.describe(channel="Kênh đăng thẻ trận", enabled="Bật/tắt", shame_prefix="Tiền tố nick bêu")
    async def wc_setup(self, interaction: discord.Interaction,
                       channel: discord.TextChannel | None = None,
                       enabled: bool | None = None,
                       shame_prefix: str | None = None) -> None:
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Cần quyền **Manage Server**.", ephemeral=True)
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
                await interaction.followup.send("❌ Server chưa khởi tạo.", ephemeral=True)
                return
            cfg = await WCConfigRepository(session).upsert(guild.id, data)
            ch = f"<#{cfg.channel_id}>" if cfg.channel_id else "(chưa đặt)"
            state = "BẬT ✅" if cfg.enabled else "TẮT ⛔"
        await interaction.followup.send(
            f"⚙️ WC Predict: {state} • kênh {ch} • prefix nick bêu `{cfg.shame_nick_prefix}`",
            ephemeral=True,
        )
```

- [ ] **Step 4: Chạy test helper** → PASS (`.venv/bin/pytest tests/unit/test_wc_predict_helpers.py -q`).

- [ ] **Step 5: Lint + commit** (chưa đăng ký cog — làm ở Task 7)

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

### Task 6: Cog `wc_sync` — loop sync → đăng thẻ → settle

**Glue — verify thủ công.** Nhịp 2–5 phút: (1) `sync_matches`; (2) với mỗi guild bật, đăng thẻ
trận sắp đá (trong cửa sổ trước kickoff, chưa đăng) + thả sẵn 2 cờ; (3) `settle_finished`; (4) khoá
thẻ tới giờ (sửa footer + gỡ view).

**Files:** Create `app/bot/cogs/wc_sync.py`.

- [ ] **Step 1: Viết `app/bot/cogs/wc_sync.py`** (bám `subscription.py`/`companion.py`):

```python
"""Cog WC Sync — loop: đồng bộ trận từ API, đăng thẻ trận sắp đá, chấm trận đã xong, khoá thẻ.

Pattern theo SubscriptionCog: session_scope mỗi nhịp, lỗi 1 nhịp không giết loop. Chỉ đăng thẻ cho
guild đã /wc-setup (enabled + channel_id). Dùng wc_card chống đăng lại.
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
from app.services.wc.cards import build_match_embed, flag_pair := None  # xem chú thích dưới
from app.services.wc.flags import flag
from app.services.wc.sync_service import settle_finished, sync_matches
from app.bot.cogs.wc_predict import build_card_view

log = logging.getLogger(__name__)

SYNC_MINUTES = 3
POST_WINDOW_HOURS = 12  # đăng thẻ khi trận còn <= 12h tới giờ


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
            # Trận scheduled trong cửa sổ (đơn giản: lấy finished_unsettled không hợp; ta cần query riêng)
            upcoming = await mrepo.upcoming(now, horizon)  # THÊM method này, xem ghi chú
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
                        # thả sẵn 2 cờ để đoán nhanh
                        for code in (match.home_code, match.away_code):
                            try:
                                await msg.add_reaction(flag(code))
                            except discord.DiscordException:
                                pass
                    except discord.DiscordException:
                        log.warning("wc: post card failed guild=%s match=%s", cfg.guild_id, match.id)
```

> **Ghi chú khi code Task 6:**
> - Bỏ dòng `flag_pair := None` (placeholder import sai) — chỉ cần `from app.services.wc.flags import flag`.
> - Thêm `WCMatchRepository.upcoming(self, start, end)` vào `app/repositories/wc_match.py`:
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
>   (Thêm 1 test nhỏ trong `tests/unit/test_wc_repos.py` cho `upcoming`.)
> - **Khoá thẻ tới giờ:** thêm bước trong `_post_due_cards` hoặc 1 method riêng: với mỗi
>   `crepo.unlocked_cards()` mà `match.kickoff_at <= now` → fetch message
>   (`channel.fetch_message(card.message_id)`), `await msg.edit(embed=build_match_embed(match,
>   locked=True), view=None)`, `await crepo.mark_locked(card.guild_id, card.match_id)`.

- [ ] **Step 2: Thêm `upcoming` + test, chạy `.venv/bin/pytest -q`** (suite phải xanh).

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

### Task 7: Đăng ký cog + persistent items trong `client.py`

**Files:** Modify `app/bot/client.py`.

- [ ] **Step 1: Sửa `setup_hook`** trong `app/bot/client.py` — thêm import + đăng ký 2 cog + đăng ký
  DynamicItem để nút persistent hoạt động sau restart. Thêm gần các `add_cog` khác:

```python
from app.bot.cogs.wc_predict import WCButton, WCPredictCog
from app.bot.cogs.wc_sync import WCSyncCog
# ... trong setup_hook, trước self.tree.sync():
self.add_dynamic_items(WCButton)
await self.add_cog(WCPredictCog(self, self.discord_io))
await self.add_cog(WCSyncCog(self, self.discord_io))
```

> `add_dynamic_items` đăng ký lớp nút động để Discord route lại click sau restart (discord.py 2.4).
> Nếu phiên bản discord.py không có `add_dynamic_items`, dùng `self.add_view` với view persistent +
> `WCButton.from_custom_id` — kiểm tra `discord.__version__` khi code.

- [ ] **Step 2: Khởi động bot, `docker compose logs -f api`** xác nhận: "Cogs loaded", không lỗi
  import, loop `wc_tick` chạy.

- [ ] **Step 3: Commit**

```bash
git add app/bot/client.py
git commit -F - <<'EOF'
feat(wc): register wc_predict + wc_sync cogs + persistent buttons

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

---

## Manual verification checklist (trên server thật)

Cần `FOOTBALL_DATA_API_KEY` trong env + có trận WC sắp đá (hoặc tạm seed 1 `wc_match` scheduled
trong DB để test thẻ).

- [ ] `/wc-setup channel:#kèo enabled:true` → báo BẬT + đúng kênh.
- [ ] Trong ≤ `SYNC_MINUTES`+`POST_WINDOW`, thẻ trận hiện ở kênh: tiêu đề có **cờ 2 đội**, giờ VN
  đúng (UTC+7), nút 1X2/Tài-Xỉu/Cửa-trên-dưới/🎯, và bot đã thả sẵn 2 cờ.
- [ ] Bấm nút 1X2 → ephemeral "✅ Đã ghi kèo". Bấm lại pick khác → cập nhật (không tạo trùng — kiểm
  DB `wc_prediction` chỉ 1 dòng/bet_type).
- [ ] Bấm 🎯 → modal hiện → nhập `2-1` → "✅ ... (tỉ số 2-1)". Nhập `abc` → "❌ không hợp lệ".
- [ ] Thả cờ đội nhà → tạo prediction 1x2 home (kiểm DB). Gỡ cờ → xoá prediction đó.
- [ ] Sau kickoff: bấm nút → "🔒 Trận đã khoá kèo". Thẻ được sửa footer "🔒 Đã khoá" + mất nút.
- [ ] Khi trận `finished` có tỉ số: trong ≤ `SYNC_MINUTES`, `wc_prediction.points` được điền đúng
  (so với `scoring.score`), `wc_match.settled=true`, không chấm lại nhịp sau.
- [ ] **Restart bot** → bấm nút trên thẻ cũ vẫn hoạt động (persistent view OK).
- [ ] `/wc-setup enabled:false` → ngừng đăng thẻ mới.

## Self-review (rà trước khi bàn giao)

- **Spec coverage Pha 2:** sync loop ✅; đăng thẻ cờ+nút ✅; modal tỉ số ✅; thả-cờ quick-1X2 ✅;
  khoá tại kickoff ✅; settle tự động ✅; `/wc-setup` (bật/kênh/prefix) ✅. (BXH/phạt/AI = Pha 3-4.)
- **Type consistency:** `pick` values khớp `_PICK_LABEL` + `scoring.score`; `build_custom_id`/
  `parse_custom_id`/`WCButton.template` cùng format `wc:bet:pick:match`; `WCMatchRepository.upcoming`
  trả `list[WCMatch]` khớp `_post_due_cards`.
- **Edge:** trận finished chưa có tỉ số → settle bỏ qua; channel bị xoá → `get_channel` None → skip;
  thẻ đã đăng → `crepo.exists` chặn trùng.
