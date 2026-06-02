# WC Predict — Giải dự đoán World Cup theo server

Bộ plan triển khai tính năng **WC Predict** cho rolt9 (bot Discord). Mỗi server tự tổ chức một
"giải dự đoán" các trận World Cup: bot kéo lịch từ API bóng đá free, đăng thẻ trận có cờ + nút
bấm, người chơi đoán; trận xong bot tự chấm điểm, lên BXH mùa; cuối mỗi vòng đứa bét bảng bị AI
cà khịa + đổi nickname bêu. **Danh dự, KHÔNG tiền ảo, KHÔNG trừ điểm** — đoán sai chỉ ăn 0.

> File này + các plan trong thư mục này là **tài liệu làm việc** (đọc được trên mọi máy đã clone
> repo). Bám đúng pattern repo đã trích trong từng plan. Stack: Python 3.12, FastAPI, SQLAlchemy 2
> async, Alembic, discord.py 2.4, pytest, AIGateway (BYO-key per-guild), football-data.org.

## Bản đồ các pha

| Pha | File | Nội dung | Trạng thái |
|---|---|---|---|
| — | [`00-spec.md`](00-spec.md) | Spec thiết kế gốc (đã chốt) | ✅ |
| 1 | (code đã trong repo) | Nền tảng: scoring + models + repos + API client | ✅ **DONE** (merged `feat/claw-agent`) |
| 2 | [`02-phase2-discord.md`](02-phase2-discord.md) | Cog sync (loop kéo trận + chấm điểm), thẻ trận (cờ + nút + modal + thả-cờ), `/wc-setup` | ⏳ TODO |
| 3 | [`03-phase3-leaderboard-punishment.md`](03-phase3-leaderboard-punishment.md) | BXH (`/wc-bxh`, `/wc-cua-toi`) + phạt đổi-nick + AI roast bét bảng | ⏳ TODO |
| 4 | [`04-phase4-ai.md`](04-phase4-ai.md) | AI: tư vấn kèo / đoán-bằng-lời (tool agent) / hot-take thẻ trận | ⏳ TODO |

## Pha 1 đã có gì (nền tảng — đừng làm lại)

Đã code + test + push trên nhánh `feat/claw-agent`:

- **`app/services/wc/scoring.py`** — `POINTS = {"1x2": 1, "ou": 1, "ah": 2, "cs": 5}` và
  `score(bet_type, pick, *, home_score, away_score, ou_line=None, handicap_team=None, handicap_line=None) -> int`.
  Thuần, không I/O. Sai/push = 0. Kèo chấp châu Á v1 chỉ mốc nguyên/nửa (không có chấp 1/4).
- **Models** (`app/models/`): `wc_match` (PK = API match id, dùng chung mọi guild),
  `wc_prediction` (UNIQUE `guild_id,match_id,user_discord_id,bet_type`), `guild_wc_config`
  (`enabled`/`channel_id`/`shame_nick_prefix` mặc định `"🤡 Non Tay — "`), `wc_shame`
  (`original_nick`). Đã đăng ký trong `app/db/base.py`. Migration `c0ffee0wc001`.
- **Repos** (`app/repositories/`): `WCMatchRepository` (`upsert`/`finished_unsettled`/
  `mark_settled`/`get`), `WCPredictionRepository` (`upsert`/`for_match`/`for_user_match`/
  `set_points`/`leaderboard`), `WCConfigRepository` (`get`/`get_or_create`/`upsert`/`all_enabled`).
- **`app/services/wc/football_api.py`** — `fetch_wc_matches() -> list[dict]` gọi
  football-data.org `/v4/competitions/WC/matches`, map field, lỗi/thiếu key → `[]` (không raise).
  Env key `FOOTBALL_DATA_API_KEY` (đã thêm vào `app/core/config.py`).

Tests Pha 1: `tests/unit/test_wc_scoring.py`, `test_wc_models.py`, `test_wc_repos.py`,
`test_wc_football_api.py` — tất cả pass (23 test).

## Trước khi chạy thật (Pha 2 cần)

1. Đăng ký free tại <https://www.football-data.org/> lấy API token.
2. Bỏ vào env: `FOOTBALL_DATA_API_KEY=<token>` (file `.env` / compose env). Rỗng = tắt sync, an toàn.
3. Free tier ~10 request/phút — loop sync để 2–5 phút/nhịp là dư.

## Quy ước chung khi code (đã verify trong repo)

- **Cog KHÔNG dùng `setup(bot)`/`load_extension`.** Đăng ký thủ công trong
  `app/bot/client.py` → `setup_hook()` bằng `await self.add_cog(XxxCog(self, self.discord_io))`,
  rồi `await self.tree.sync()` ở cuối (đã có sẵn).
- **DB session:** `from app.db.session import session_scope` rồi `async with session_scope() as session:`
  (tự commit khi thoát, rollback khi lỗi). Repo flush-only, commit ở boundary.
- **Map guild:** `discord.Guild.id` (snowflake) → UUID nội bộ qua
  `await GuildRepository(session).get_by_discord_id(int(guild.id))` → `.id` là UUID dùng cho FK.
- **AIGateway per-guild:** dựng mới trong session (xem `_gateway(session)` ở `subscription.py`),
  gọi `await gw.complete(guild_discord_id=..., system=..., prompt=...)`. Lỗi (AI off/hết key/quá
  budget/rỗng) → raise `ValueError`; luôn `try/except ValueError` và bỏ qua/`❌ {exc}`.
- **Loop cog:** `@tasks.loop(...)`, start ở `cog_load`, cancel ở `cog_unload`,
  `@loop.before_loop` → `await self.bot.wait_until_ready()`. Bọc thân loop trong
  `try/except Exception` để 1 nhịp lỗi không giết loop.
- **Slash command:** `@app_commands.command(...)` hoặc `app_commands.Group(name=..., guild_only=True)`;
  check quyền admin bằng `if not interaction.user.guild_permissions.manage_guild: ... return`
  (xem `agent.py claw-lore-clear`). `await interaction.response.defer()` rồi `followup.send(...)`.
- **Lint + test trước mỗi commit:** `.venv/bin/ruff format <files>` → `.venv/bin/ruff check <files>`
  → `.venv/bin/pytest -q`. Commit message theo Conventional Commits (commitizen pre-commit), kết
  dòng `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- **Cog/Discord-glue không có hạ tầng unit-test** trong repo (chỉ service/pure được test). Vì vậy
  các plan tách phần **logic thuần/service** ra để unit-test, còn phần **glue Discord** verify thủ
  công trên server thật (checklist cuối mỗi plan).
