# WC Predict — Pha 4: AI (tư vấn kèo / đoán-bằng-lời / hot-take) (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Chất rolt9 phủ lên WC Predict: (1) **đoán bằng lời** — "@rolt9 tao đoán Brazil 2-1" → tool
agent parse + ghi `wc_prediction`; (2) **tư vấn kèo** — "@rolt9 nên đoán đội nào" → agent dùng
`web_search` (đã có) + biết ngữ cảnh WC; (3) **hot-take thẻ trận** — thẻ đăng kèm 1 câu bình bựa
(tùy chọn; lỗi/AI off → thẻ vẫn đăng).

**Architecture:** Thêm 1 tool `wc_predict` vào agent (tools/registry.py spec + handler ghi DB).
Tư vấn kèo chỉ cần nudge persona (web_search có sẵn). Hot-take = 1 lệnh gọi `AIGateway.complete`
ngắn trong cog `wc_sync` lúc đăng thẻ, truyền vào `build_match_embed(hot_take=...)` (param đã có
từ Pha 2). Mọi nhánh AI bọc try/except để không bao giờ làm hỏng luồng chính.

**Tech Stack:** AIGateway (`complete`/`complete_raw` tool-loop), tools/actions registry, pytest.
Phụ thuộc Pha 1+2 (+3 nếu muốn roast dùng chung). **Đọc trước:** `app/services/ai/tools/registry.py`,
`app/services/ai/actions/registry.py`, `app/services/ai/agent_service.py` để bám đúng cách 1 tool
được khai báo + dispatch trong repo (cấu trúc spec + handler hiện hành).

---

## File structure

| File | Trách nhiệm | Test? |
|---|---|---|
| `app/services/wc/nl_predict.py` | Parse "đoán <đội> <tỉ số>/thắng/thua/tài/xỉu" → (bet_type, pick) + resolve match | ✅ unit |
| `app/services/ai/tools/registry.py` (sửa) | Thêm spec + handler tool `wc_predict` | theo test routing repo |
| `app/services/ai/agent_service.py` (sửa) | Nudge ngữ cảnh WC (tư vấn kèo + biết tool wc_predict) | — |
| `app/bot/cogs/wc_sync.py` (sửa) | Sinh hot-take khi đăng thẻ (tùy chọn) | manual |
| `app/services/wc/hot_take.py` | build prompt hot-take 1 câu | ✅ unit (build) |

---

### Task 1: `nl_predict.py` — parse dự đoán bằng lời

**Files:** Create `app/services/wc/nl_predict.py`; Test `tests/unit/test_wc_nl_predict.py`.

Mục tiêu: từ câu/đối số đã được agent bóc (tên đội + ý đồ), suy ra `(bet_type, pick)`. Việc khớp
ĐỘI → `match_id` để cho handler (cần DB). Hàm thuần ở đây chỉ lo bet/pick từ text.

- [ ] **Step 1: Test** `tests/unit/test_wc_nl_predict.py`:

```python
import pytest

from app.services.wc.nl_predict import parse_intent


@pytest.mark.parametrize("text,team_side,expected", [
    ("tao đoán Brazil 2-1", "home", ("cs", "2-1")),
    ("Brazil thắng", "home", ("1x2", "home")),
    ("kèo này hòa", None, ("1x2", "draw")),
    ("Argentina thắng", "away", ("1x2", "away")),
    ("tài", None, ("ou", "over")),
    ("xỉu đi", None, ("ou", "under")),
])
def test_parse_intent(text, team_side, expected):
    assert parse_intent(text, team_side=team_side) == expected


def test_unparseable_returns_none():
    assert parse_intent("ờ chắc vậy", team_side=None) is None
```

- [ ] **Step 2: FAIL → Step 3: `app/services/wc/nl_predict.py`**:

```python
"""Suy luận (bet_type, pick) từ lời người chơi cho WC. THUẦN — agent lo khớp đội→match_id.

team_side = vị trí đội người chơi nhắc trong trận đó ('home'/'away'/None) do agent xác định trước.
Ưu tiên: tỉ số (cs) > tài/xỉu (ou) > thắng-thua-hòa (1x2). Không suy được -> None.
"""
import re

_SCORE = re.compile(r"\b(\d{1,2})\s*[-:]\s*(\d{1,2})\b")


def parse_intent(text: str, *, team_side: str | None) -> tuple[str, str] | None:
    t = (text or "").lower()
    m = _SCORE.search(t)
    if m:
        return "cs", f"{int(m.group(1))}-{int(m.group(2))}"
    if "tài" in t or "tai" in t or "over" in t:
        return "ou", "over"
    if "xỉu" in t or "xiu" in t or "under" in t:
        return "ou", "under"
    if "hòa" in t or "hoa" in t or "draw" in t:
        return "1x2", "draw"
    if "thắng" in t or "thang" in t or "win" in t:
        if team_side in ("home", "away"):
            return "1x2", team_side
    if "thua" in t or "lose" in t:
        if team_side == "home":
            return "1x2", "away"
        if team_side == "away":
            return "1x2", "home"
    return None
```

- [ ] **Step 4: PASS → commit** `feat(wc): natural-language prediction intent parser`.

---

### Task 2: Tool `wc_predict` cho agent

**Đọc `app/services/ai/tools/registry.py` trước** để khớp đúng cấu trúc spec + handler hiện có
(các tool như `remind`, `subscribe`, `forget` khai báo thế nào, handler nhận gì, trả gì, lấy
`session`/`guild` ra sao). Làm theo y hệt.

- [ ] **Step 1: Spec tool** (thêm cạnh các spec khác) — tham số:
  - `team` (string, bắt buộc): tên đội người chơi nhắc (vd "Brazil").
  - `intent` (string, bắt buộc): nguyên văn ý người chơi (vd "2-1", "thắng", "tài") để
    `parse_intent` xử lý.
  - Mô tả tool: "Ghi dự đoán World Cup của người dùng cho trận sắp đá. Dùng khi người dùng nói kiểu
    'tao đoán <đội> <tỉ số/thắng/thua/tài/xỉu>'. Chỉ ghi nếu tìm được trận sắp đá của đội đó."

- [ ] **Step 2: Handler `wc_predict`** (theo pattern handler khác trong file):
  1. `guild = GuildRepository(session).get_by_discord_id(...)`.
  2. Tìm trận sắp đá khớp `team`: query `wc_match` `status=scheduled`, `kickoff_at >= now`, tên/
     code chứa `team` (ilike) — lấy trận gần nhất. Không thấy → trả "Không tìm thấy trận sắp đá của
     {team}." (báo thật, không bịa — theo nguyên tắc CRUD execute-then-report của repo).
  3. Xác định `team_side`: 'home' nếu khớp home_team/home_code, else 'away'.
  4. `res = parse_intent(intent, team_side=team_side)`; None → "Chưa rõ đoán kiểu gì (tỉ số/thắng/
     thua/tài/xỉu)?".
  5. Check khoá (`is_locked`) → "🔒 Trận đã khoá kèo.".
  6. `WCPredictionRepository.upsert(guild.id, match.id, user_id, bet, pick)` → trả xác nhận có tên
     trận + kèo (vd "✅ Ghi kèo: Brazil 2-1 (Brazil vs Argentina).").

- [ ] **Step 3: Test routing bằng slang/colloquial** (theo thói quen repo — probe agent thật trong
  container với nhiều cách nói: "tao đoán brazil 2 1", "kèo brazil thắng nha", "trận tối nay tài
  đi") xác nhận tool `wc_predict` THỰC SỰ được gọi (không chỉ chat). Ghi lại kết quả probe.

- [ ] **Step 4:** Lint + `.venv/bin/pytest -q` + commit `feat(wc): agent tool to record predictions by voice`.

---

### Task 3: Nudge ngữ cảnh WC (tư vấn kèo)

**Files:** Modify `app/services/ai/agent_service.py`.

- [ ] Thêm vào `_TOOL_NUDGE` (hoặc system) 1 đoạn ngắn: khi người dùng hỏi "nên đoán đội nào / kèo
  trận X" → DÙNG `web_search` tra phong độ/đội hình thật rồi phán **bựa** (giữ giọng rolt9), KHÔNG
  bịa số liệu; khi người dùng nói "tao đoán ..." → gọi tool `wc_predict`. Giữ ngắn gọn (nudge dài
  làm loãng prompt). Không cần test riêng — verify qua probe ở Task 2/manual.
- [ ] Commit `feat(wc): nudge agent for WC tips + voice predictions`.

---

### Task 4: Hot-take thẻ trận

**Files:** Create `app/services/wc/hot_take.py`; Modify `app/bot/cogs/wc_sync.py`.

- [ ] **Step 1: `app/services/wc/hot_take.py`** + test (build prompt chứa 2 tên đội):

```python
"""Prompt hot-take 1 câu cho thẻ trận WC (giọng bựa rolt9). Lỗi/AI off -> cog bỏ qua, thẻ vẫn đăng."""


def build_hot_take_system(persona: str | None) -> str:
    base = "Mày là rolt9 bựa. Cho 1 CÂU bình luận cà khịa/hài về trận sắp đá. Tiếng Việt, <= 25 từ."
    return f"{base}\nPersona: {persona}" if persona else base


def build_hot_take_prompt(home: str, away: str) -> str:
    return f"Trận sắp đá: {home} vs {away}. Cho đúng 1 câu hot-take bựa."
```

- [ ] **Step 2: Trong `_post_due_cards` (cog `wc_sync`)** trước khi `channel.send`: thử sinh hot-take
  (bọc try/except ValueError + Exception, timeout ngắn). Lấy `persona` từ `AIConfigRepository`:
  ```python
  hot = None
  try:
      hot = await _gateway(session).complete(
          guild_discord_id=<discord_guild_id>,
          system=build_hot_take_system(persona),
          prompt=build_hot_take_prompt(match.home_team, match.away_team),
          max_tokens=80,
      )
  except Exception:  # noqa: BLE001 — AI off/lỗi -> thẻ vẫn đăng không hot-take
      hot = None
  embed = build_match_embed(match, locked=False, hot_take=hot)
  ```
  > Cần `discord_guild_id` (snowflake) ở đây — map ngược từ `cfg.guild_id` (UUID) qua
  > `GuildRepository.get(...)`/`bot.get_guild` hoặc dùng `channel.guild.id`. Đơn giản nhất:
  > `channel.guild.id` sau khi đã `get_channel`.
  > **Tránh tốn token:** chỉ sinh hot-take 1 lần/thẻ (đằng nào thẻ chỉ đăng 1 lần nhờ `wc_card`).

- [ ] **Step 3:** Lint + `.venv/bin/pytest -q` + commit `feat(wc): AI hot-take line on match cards`.

---

## Manual verification (server thật, AI bật + có key)

- [ ] "@rolt9 tao đoán Brazil 2-1" (+ vài biến thể slang) → bot gọi tool, ghi kèo, xác nhận đúng
  trận + tỉ số; kiểm `wc_prediction`.
- [ ] "@rolt9 trận Brazil vs Argentina nên đoán ai" → bot search web rồi phán có dẫn chứng + giọng bựa.
- [ ] Đoán đội không có trận sắp đá → bot báo "không tìm thấy trận" (KHÔNG bịa).
- [ ] Sau kickoff → "tao đoán..." → bot báo đã khoá.
- [ ] Thẻ trận mới có thêm 1 dòng *hot-take*; khi AI off/hết key → thẻ vẫn đăng bình thường, không lỗi.

## Self-review

- **Spec coverage Pha 4:** đoán-bằng-lời (tool) ✅; tư vấn kèo (web_search + nudge) ✅; hot-take ✅;
  mọi nhánh AI fail-safe (lỗi → không phá luồng) ✅.
- **Type consistency:** `parse_intent` trả `(bet_type, pick)` khớp `WCPredictionRepository.upsert` +
  `scoring.score`; `bet_type` ∈ `{1x2,ou,cs}` (ah khó nói bằng lời → bỏ ở v1, chỉ qua nút —
  ghi chú: nếu cần ah bằng lời, mở rộng `parse_intent` sau).
- **An toàn token/độ ồn:** hot-take 1 lần/thẻ; tư vấn kèo chỉ khi người dùng hỏi.
