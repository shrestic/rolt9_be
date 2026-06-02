# WC Predict — Giải dự đoán World Cup theo server (thiết kế)

**Ngày:** 2026-06-02
**Trạng thái:** Đã chốt qua brainstorming. (Bản sao tracked của spec gốc trong `docs/superpowers/specs/`.)

## Mục tiêu (1 câu)

Mỗi Discord server tổ chức một "giải dự đoán" các trận World Cup: bot tự kéo lịch từ
API bóng đá free, đăng thẻ trận có cờ + nút bấm, người chơi đoán; trận xong bot tự chấm
điểm, lên BXH mùa; cuối mỗi vòng đứa bét bảng bị AI cà khịa + đổi nickname bêu. **Danh dự,
KHÔNG tiền ảo, KHÔNG trừ điểm** — đoán sai chỉ ăn 0, không mất gì.

## Vì sao khác "cá độ thường"

Không có ví/tiền/điểm-bị-mất. Đây là giải **tài phán** kiểu tipping/fantasy: tích điểm khi
đoán đúng, đua top BXH; gia vị drama là hình phạt VUI (đổi nick + roast) cho người bét, do
AI bựa của rolt9 thực hiện.

## Phạm vi kèo (4 kiểu) + chấm điểm

Điểm theo độ khó (số mặc định, chỉnh được trong config/hằng số):

| Kiểu | Mô tả | Điểm khi đúng |
|---|---|---|
| **1X2** | Đội nhà thắng / hòa / đội khách thắng | 1 |
| **Tài/Xỉu** | Tổng bàn Over/Under mốc (mặc định 2.5) | 1 |
| **Kèo chấp châu Á** | Đội mạnh chấp 0.5/1/1.5… (CHỈ mốc nguyên/nửa, KHÔNG có chấp 1/4 nửa-thắng-nửa-thua ở v1) | 2 |
| **Tỉ số chính xác** | Đoán đúng tỉ số cuối trận | 5 |

Sai = 0 điểm (không âm). Mỗi (người, trận, kiểu kèo) một dự đoán; **sửa được tới lúc bóng lăn**.

## Nguồn dữ liệu

**football-data.org free tier** (có competition World Cup, ~10 req/phút). Key global qua env
(`FOOTBALL_DATA_API_KEY`). Lấy: lịch trận (2 đội, giờ kickoff UTC), trạng thái, tỉ số cuối.
Lỗi/giới hạn → skip nhịp, thử lại (giống SubscriptionCog). Trận hoãn/đổi giờ → cập nhật theo
API; kết quả sửa hiếm → chấm lại.

## DB (bảng mới)

- **`wc_match`** (DÙNG CHUNG mọi guild): `id` (= API match id), `competition`, `stage`, `matchday`,
  `home_team`, `home_code`, `away_team`, `away_code`, `kickoff_at` (UTC, index), `status`
  (scheduled/in_play/finished), `home_score`, `away_score`, `ou_line` (mặc định 2.5),
  `handicap_team` (home/away), `handicap_line`, `settled`, `created_at`, `updated_at`.
- **`wc_prediction`**: `id`, `guild_id` (FK guilds), `match_id` (FK wc_match), `user_discord_id`,
  `bet_type` (`1x2|ou|cs|ah`), `pick` (vd `home`/`over`/`2-1`/`favorite`), `points` (nullable),
  `created_at`. UNIQUE (`guild_id`,`match_id`,`user_discord_id`,`bet_type`). Index (`guild_id`,`match_id`).
- **`guild_wc_config`**: `guild_id` (PK/FK), `enabled`, `channel_id`, `shame_nick_prefix`
  (mặc định `🤡 Non Tay — `), `created_at`, `updated_at`.
- **`wc_shame`**: `guild_id`, `user_discord_id`, `original_nick` (nullable), `applied_at`.

## Thành phần

- **`services/wc/football_api.py`** — client football-data.org. Lỗi → trả rỗng/None, không raise.
- **`repositories/wc_match.py`, `wc_prediction.py`, `wc_config.py`** — data access.
- **`services/wc/scoring.py`** — PURE: `score(...)` → điểm.
- **`cogs/wc_sync.py`** — `tasks.loop`: (1) sync `wc_match` từ API; (2) đăng thẻ trận sắp diễn
  ra; (3) trận `finished` chưa chấm → chấm toàn bộ prediction → ghi `points`. Cờ "đã đăng"/"đã chấm".
- **`cogs/wc_predict.py`** — thẻ trận (Embed: cờ + tên đội + giờ VN) + nút 1X2/Tài-Xỉu/chấp,
  nút "🎯 Đoán tỉ số" → modal, thả cờ 1X2 nhanh, ghi/sửa prediction, KHOÁ tại kickoff. Lệnh
  `/wc-bxh`, `/wc-cua-toi`, `/wc-setup`.
- **Punishment** — "VÒNG" = `stage`/`matchday`; KẾT THÚC khi mọi trận thuộc vòng đã `finished`.
  Người ít điểm nhất guild → AI roast + đổi nickname (prefix), lưu nick gốc; sang vòng mới → trả
  nick. Chủ server / role ≥ bot → chỉ roast, bỏ đổi nick.

## Tích hợp AI

- **Roast bét bảng**: AI sinh câu cà khịa cá nhân hoá khi phạt.
- **Tư vấn kèo**: "@rolt9 nên đoán đội nào" → agent dùng `web_search` → phán bựa (tool có sẵn).
- **Đoán bằng lời**: "@rolt9 tao đoán Brazil 2-1" → tool mới `wc_predict` parse + ghi.
- **Hot-take thẻ trận**: khi đăng thẻ, AI thêm 1 câu bình luận bựa (tùy chọn, lỗi → thẻ vẫn đăng).

## Cấu hình

`/wc-setup` (cần Manage Server): bật/tắt, chọn kênh, đặt prefix nick bêu. Cần bot có **Manage
Nicknames** để phạt — thiếu thì skip đổi nick, vẫn roast. Trang FE dashboard làm SAU (ngoài phạm vi).

## Edge cases

- API lỗi/limit → skip nhịp, không crash. Trận hoãn/đổi giờ → cập nhật `kickoff_at`.
- Kết quả sửa sau khi chấm (hiếm) → chấm lại. Người rời server → giữ prediction, BXH bỏ qua nếu
  không resolve. Đổi nick: owner/role cao hơn bot → chỉ roast. Thả cờ nhầm rồi gỡ → huỷ dự đoán
  1X2 tương ứng (chỉ trước kickoff).

## Ngoài phạm vi (v1)

Kèo chấp 1/4; BTTS / cầu thủ ghi bàn / vô địch giải (outright); trang FE dashboard; cá cược bằng
tiền/điểm có-mất.
