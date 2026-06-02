# WC Predict — Pha 3: BXH + Phạt đổi-nick + AI roast (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** `/wc-bxh` (BXH mùa) + `/wc-cua-toi` (kèo của tôi). Cuối mỗi VÒNG, người ít điểm nhất guild
bị AI cà khịa công khai + đổi nickname bêu (lưu nick gốc); sang vòng mới trả nick. Owner/role ≥ bot
→ chỉ roast, bỏ đổi nick.

**Architecture:** Logic chia vòng (`rounds.py`) + chọn bét-bảng tách thuần để test; AI roast qua
AIGateway per-guild; đổi nick + guard quyền là glue Discord (theo guard sẵn ở `actions/registry.py`).
Bảng `wc_round` chống phạt lại 1 vòng.

**Tech Stack:** discord.py 2.4 (`member.edit(nick=...)`, app_commands), SQLAlchemy 2 async, Alembic,
AIGateway, pytest. Phụ thuộc Pha 1+2.

---

## File structure

| File | Trách nhiệm | Test? |
|---|---|---|
| `app/services/wc/rounds.py` | `round_key(match)`, `completed_rounds(matches)` | ✅ unit |
| `app/services/wc/standings.py` | chọn bét-bảng từ leaderboard (lọc member còn trong guild) | ✅ unit |
| `app/services/wc/roast_service.py` | build system/prompt roast bét-bảng | ✅ unit (build prompt) |
| `app/models/wc_round.py` + repo + migration | bảng `wc_round` (vòng đã phạt + ai bị phạt) | — / ✅ repo |
| `app/bot/cogs/wc_predict.py` (sửa) | thêm `/wc-bxh`, `/wc-cua-toi` | manual |
| `app/bot/cogs/wc_sync.py` (sửa) | sau settle → phạt vòng mới hoàn tất | manual |

---

### Task 1: `rounds.py` — chia vòng + vòng đã hoàn tất

"VÒNG" = `stage` + `matchday` (vd `GROUP_STAGE:1`, `ROUND_OF_16:None`). Một vòng KẾT THÚC khi MỌI
trận thuộc vòng đó đã `settled`.

**Files:** Create `app/services/wc/rounds.py`; Test `tests/unit/test_wc_rounds.py`.

- [ ] **Step 1: Test thất bại** `tests/unit/test_wc_rounds.py`:

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
        _M("GROUP_STAGE", 1, True), _M("GROUP_STAGE", 1, True),   # vòng đủ -> hoàn tất
        _M("GROUP_STAGE", 2, True), _M("GROUP_STAGE", 2, False),  # còn 1 trận chưa settled
    ]
    assert completed_rounds(ms) == {"GROUP_STAGE:1"}
```

- [ ] **Step 2: Chạy thất bại** → FAIL.

- [ ] **Step 3: `app/services/wc/rounds.py`**:

```python
"""Chia trận thành VÒNG (stage+matchday) và xác định vòng đã hoàn tất (mọi trận settled). PURE."""
from collections import defaultdict


def round_key(match) -> str:
    """Khoá vòng ổn định: 'STAGE:matchday' ('-' nếu matchday None)."""
    md = match.matchday if match.matchday is not None else "-"
    return f"{match.stage}:{md}"


def completed_rounds(matches) -> set[str]:
    """Tập round_key mà MỌI trận thuộc vòng đó đều settled (và vòng có ít nhất 1 trận)."""
    groups: dict[str, list] = defaultdict(list)
    for m in matches:
        if m.stage is None:
            continue
        groups[round_key(m)].append(m)
    return {k for k, ms in groups.items() if ms and all(m.settled for m in ms)}
```

- [ ] **Step 4: PASS** → commit `feat(wc): round grouping + completion detection`.

---

### Task 2: `standings.py` — chọn người bét bảng

**Files:** Create `app/services/wc/standings.py`; Test `tests/unit/test_wc_standings.py`.

Leaderboard (Pha 1 repo) trả `[(user_id, total)]` giảm dần. Bét-bảng = điểm thấp nhất TRONG SỐ
member còn trong guild; cần ≥ 2 người chơi mới phạt (tránh phạt người chơi duy nhất). Hoà bét →
chọn ai? → chọn người có user_id nhỏ nhất (ổn định) hoặc bỏ phạt nếu hoà nhiều — chọn: phạt 1 người
(nhỏ nhất) cho đơn giản; ghi chú trong code.

- [ ] **Step 1: Test** `tests/unit/test_wc_standings.py`:

```python
from app.services.wc.standings import pick_loser


def test_pick_loser_lowest_among_members():
    lb = [(1, 10), (2, 3), (3, 8)]  # giảm dần đã sort ở repo; đây test logic chọn min
    members = {1, 2, 3}
    assert pick_loser(lb, members) == 2


def test_skip_when_fewer_than_two_players():
    assert pick_loser([(1, 5)], {1}) is None
    assert pick_loser([], set()) is None


def test_ignore_users_left_guild():
    lb = [(1, 10), (2, 1), (3, 8)]
    assert pick_loser(lb, {1, 3}) == 3  # user 2 đã rời -> bỏ qua
```

- [ ] **Step 2: FAIL → Step 3: `app/services/wc/standings.py`**:

```python
"""Chọn người bét bảng để phạt (thuần). Lọc theo member còn trong guild; cần >= 2 người chơi."""


def pick_loser(leaderboard: list[tuple[int, int]], member_ids: set[int]) -> int | None:
    """leaderboard = [(user_id, total)] (mọi thứ tự). Trả user_id điểm thấp nhất CÓ trong member_ids,
    None nếu < 2 người chơi hợp lệ. Hoà bét -> chọn user_id nhỏ nhất (ổn định)."""
    valid = [(uid, pts) for uid, pts in leaderboard if uid in member_ids]
    if len(valid) < 2:
        return None
    low = min(pts for _, pts in valid)
    return min(uid for uid, pts in valid if pts == low)
```

- [ ] **Step 4: PASS → commit** `feat(wc): pick lowest scorer (filter members, need 2+)`.

---

### Task 3: `roast_service.py` — prompt cà khịa

**Files:** Create `app/services/wc/roast_service.py`; Test `tests/unit/test_wc_roast_service.py`.

- [ ] **Step 1: Test** (chỉ test build prompt chứa tên + điểm + ngữ cảnh WC):

```python
from app.services.wc.roast_service import build_roast_prompt, build_roast_system


def test_prompt_has_context():
    sys = build_roast_system("persona bựa")
    p = build_roast_prompt(name="Khôi", points=2, round_label="vòng bảng lượt 1")
    assert "Khôi" in p and "2" in p and "vòng bảng" in p
    assert "persona" in sys.lower() or len(sys) > 0
```

- [ ] **Step 2: FAIL → Step 3: `app/services/wc/roast_service.py`**:

```python
"""Prompt cho AI cà khịa người bét bảng WC. Giữ giọng bựa của rolt9; 1-2 câu, không tục tĩu nặng."""


def build_roast_system(persona: str | None) -> str:
    base = (
        "Mày là rolt9 — bot Discord bựa, lầy nhưng có duyên. Nhiệm vụ: cà khịa NGẮN (1-2 câu) "
        "người đoán bóng đá bét bảng vòng này. Hài hước, châm chọc kiểu bạn bè, KHÔNG xúc phạm "
        "nặng/phân biệt. Tiếng Việt, có thể chèn emoji."
    )
    return f"{base}\n\nPersona server: {persona}" if persona else base


def build_roast_prompt(*, name: str, points: int, round_label: str) -> str:
    return (
        f"Cà khịa {name} vì đoán bóng tệ nhất {round_label}, chỉ được {points} điểm. "
        f"1-2 câu, nhắc tên {name}."
    )
```

- [ ] **Step 4: PASS → commit** `feat(wc): roast prompt builder for bottom scorer`.

---

### Task 4: Bảng `wc_round` + repo + migration

Chống phạt lại 1 vòng + biết ai đang bị bêu để trả nick sang vòng sau.

**Files:** `app/models/wc_round.py`, `app/repositories/wc_round.py`,
`alembic/versions/<ts>_wc_round.py`, sửa `app/db/base.py`; Test `tests/unit/test_wc_round_repo.py`.

- [ ] Model `WCRound`: `id`, `guild_id` (FK), `round_key` (String), `loser_user_id` (BigInteger,
  nullable), `punished_at`. UNIQUE(`guild_id`,`round_key`).
- [ ] Repo `WCRoundRepository`: `is_punished(guild_id, round_key) -> bool`,
  `record(guild_id, round_key, loser_user_id)`, `last_loser(guild_id) -> int | None` (người bị phạt
  gần nhất, để trả nick).
- [ ] Migration `revision=e2dc0round003`, `down_revision` = head hiện tại (verify `alembic heads`).
- [ ] Test repo (is_punished False→record→True; last_loser). Apply migration. Lint + commit
  `feat(wc): wc_round table + repo (track punished rounds)`.

(Khung code y hệt `wc_card` Task 3 Pha 2 — đổi tên cột; tự suy ra.)

---

### Task 5: `/wc-bxh` + `/wc-cua-toi`

**Glue — manual.** Thêm 2 lệnh vào `app_commands.Group("wc")` ở `wc_predict.py`.

- [ ] **`/wc-bxh`**: `defer()` → `session_scope` → `lb = await WCPredictionRepository(session).leaderboard(guild.id)`
  → render Embed top N: resolve tên qua `interaction.guild.get_member(uid)` (None → "(đã rời)"), bỏ
  qua người đã rời nếu muốn. Footer "mùa World Cup". `followup.send(embed=...)`.
- [ ] **`/wc-cua-toi`**: liệt kê prediction của `interaction.user` (qua `for_user_match` từng trận
  hoặc thêm repo method `for_user(guild_id, user_id)`), kèm điểm đã chấm / "chờ đá". Ephemeral.
- [ ] Helper render (`render_leaderboard(rows, name_of) -> str`) tách thuần → test nhỏ
  `tests/unit/test_wc_render.py` (sort/format/đánh số 🥇🥈🥉).
- [ ] Lint + `.venv/bin/pytest -q` + commit `feat(wc): /wc-bxh + /wc-cua-toi commands`.

> Thêm `WCPredictionRepository.for_user(self, guild_id, user_id)` (giống `for_user_match` bỏ điều
> kiện match) nếu cần cho `/wc-cua-toi`; thêm test.

---

### Task 6: Phạt vòng mới hoàn tất (cog `wc_sync`)

**Glue — manual.** Sau `settle_finished` mỗi nhịp, kiểm vòng mới hoàn tất → phạt.

- [ ] **Step 1: Thêm method `_punish_completed_rounds(self)`** vào `WCSyncCog`, gọi sau settle trong
  `wc_tick`. Luồng (mỗi guild enabled):
  1. Lấy mọi `WCMatch` (`mrepo.all()` — thêm method) → `done = completed_rounds(matches)`.
  2. Với mỗi `rk in done` chưa `WCRoundRepository.is_punished(guild.id, rk)`:
     - `lb = leaderboard(guild.id)`; `member_ids = {m.id for m in discord_guild.members}`;
       `loser = pick_loser(lb, member_ids)`. None → vẫn `record` (đánh dấu đã xử lý, không phạt ai).
     - **Trả nick người bị phạt vòng trước:** `prev = WCRoundRepository.last_loser(guild.id)`;
       nếu có row `wc_shame` cho prev → `member.edit(nick=original_nick)` (guard quyền) → xoá row shame.
     - **Roast + đổi nick loser:** lấy `cfg.persona` (qua `AIConfigRepository`), gọi
       `AIGateway.complete(guild_discord_id=..., system=build_roast_system(persona),
       prompt=build_roast_prompt(name=member.display_name, points=..., round_label=rk))` trong
       try/except ValueError. Gửi roast vào `cfg.channel_id`.
     - **Đổi nick** (guard, theo `actions/registry.py`): bỏ qua nếu
       `member.id == discord_guild.owner_id` hoặc `discord_guild.me.top_role <= member.top_role`
       hoặc không `discord_guild.me.guild_permissions.manage_nicknames` → chỉ roast, báo nhẹ. Ngược
       lại: lưu `wc_shame(guild_id, user_id, original_nick=member.nick)` rồi
       `await member.edit(nick=f"{cfg.shame_nick_prefix}{member.display_name}"[:32])`.
     - `WCRoundRepository.record(guild.id, rk, loser_user_id=loser)`.
  3. Mọi `member.edit` / `channel.send` bọc `try/except discord.DiscordException`.

- [ ] **Step 2:** Thêm `WCMatchRepository.all()` + test. `.venv/bin/pytest -q` xanh.
- [ ] **Step 3:** Lint + commit `feat(wc): punish bottom scorer per completed round (roast + nick)`.

---

## Manual verification (server thật)

- [ ] Seed/chờ 1 vòng đủ trận `settled`. Bot đăng roast bét-bảng đúng kênh, nhắc đúng tên + điểm.
- [ ] Nick người bét đổi thành `🤡 Non Tay — <tên>` (nếu bot đủ quyền + không phải owner/role cao).
- [ ] Owner/role ≥ bot làm bét → CHỈ roast, không đổi nick, có báo nhẹ.
- [ ] Vòng KẾ hoàn tất → nick người bị phạt vòng trước được TRẢ lại; người bét vòng mới bị bêu.
- [ ] Vòng đã phạt không bị phạt lại (kiểm `wc_round`).
- [ ] `/wc-bxh` sort đúng giảm dần; `/wc-cua-toi` liệt kê kèo + điểm/chờ.
- [ ] < 2 người chơi → không phạt ai (vòng vẫn đánh dấu đã xử lý).

## Self-review

- **Spec coverage Pha 3:** BXH ✅; kèo-của-tôi ✅; phạt bét-bảng đổi-nick + lưu/trả nick gốc ✅; AI
  roast ✅; guard owner/role/quyền ✅; chống phạt lại ✅; "vòng" = stage+matchday ✅.
- **Type consistency:** `round_key` dùng nhất quán giữa `rounds.py`/`wc_round`/cog; `pick_loser` ăn
  output `leaderboard()`; prefix nick từ `guild_wc_config.shame_nick_prefix`.
