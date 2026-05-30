# Quests — Hướng dẫn & Workflow

Nhiệm vụ ngày/tuần do **admin tự tạo**. Member làm đủ tiến độ → gõ `/quests claim` nhận coin.

---

## 1. Tính năng làm gì

- Admin tạo nhiệm vụ qua dashboard: đặt **mục tiêu** (kiếm coin / điểm danh), **chu kỳ** (ngày/tuần), **target**, **coin thưởng**.
- Member chat (kiếm coin thụ động) hoặc `/daily` → tiến độ nhiệm vụ tự tăng.
- Đủ tiến độ → `/quests claim` nhận hết coin một lần.
- Tiến độ **reset theo chu kỳ**: daily reset 0h UTC, weekly reset thứ 2 0h UTC.

> **Phụ thuộc:** Quests cần **Currency bật** (mục tiêu đếm coin/điểm danh, thưởng = coin). Bật Currency trước.

---

## 2. Cho admin — tạo nhiệm vụ (Dashboard)

Vào **Dashboard → server → Quests**. Mỗi nhiệm vụ gồm:

| Trường | Ý nghĩa |
|---|---|
| **Name** | Tên hiển thị (vd "Chăm chỉ hằng ngày") |
| **Description** | Mô tả (tùy chọn) |
| **Period** | `daily` (reset mỗi ngày) hoặc `weekly` (reset mỗi tuần) |
| **Objective** | `Kiếm coin` (cộng dồn coin nhận) hoặc `Điểm danh` (đếm số lần /daily) |
| **Target** | Tiến độ cần đạt (1–100.000) |
| **Reward coins** | Coin thưởng khi hoàn thành (0–1.000.000) |
| **Enabled** | Bật/tắt nhiệm vụ |

Tạo / sửa / xóa / bật-tắt thoải mái. Tắt nhiệm vụ → không hiện với member, không tính tiến độ nữa.

**Ví dụ bộ nhiệm vụ gợi ý:**
- `daily` · Kiếm coin · target 200 · thưởng 50 → "Kiếm 200 coin hôm nay".
- `daily` · Điểm danh · target 1 · thưởng 30 → "Điểm danh hôm nay".
- `weekly` · Điểm danh · target 5 · thưởng 300 → "Điểm danh 5 ngày tuần này".
- `weekly` · Kiếm coin · target 2000 · thưởng 500 → "Kiếm 2000 coin tuần này".

---

## 3. Cho member — lệnh Discord

| Lệnh | Việc |
|---|---|
| `/quests list` | Xem nhiệm vụ + thanh tiến độ + trạng thái (đang làm / ✅ sẵn sàng / ☑️ đã nhận) |
| `/quests claim` | Nhận **tất cả** nhiệm vụ đã đủ tiến độ, báo tổng coin |

Tiến độ tăng tự động khi: **chat** (mỗi tin ăn coin → cộng vào quest "Kiếm coin"), **`/daily`** (cộng coin nhận + 1 lần điểm danh).

---

## 4. Cơ chế bên trong (cho dev)

```
Member chat → xp_listener → currency.grant_message_reward(amount)
                              └→ QuestService.record_event("earn_coins", amount)

/daily → CurrencyCog.daily → claim_daily
            └→ QuestService.record_event("earn_coins", res.amount)
            └→ QuestService.record_event("daily_claim", 1)

/quests claim → QuestService.claim (atomic try_claim mỗi quest → WalletRepository.add_balance)
```

- **Period key**: daily = ngày UTC (`2026-05-30`), weekly = ISO week (`2026-W22`). Tiến độ lưu theo `period_key` → qua kỳ là row mới, tự về 0.
- **Atomic**: `increment` cộng dồn trong SQL (không lost-update); `try_claim` là guarded UPDATE (`progress>=target AND claimed=false`) → không nhận 2 lần.
- **Decoupled**: QuestService đọc qua repos, thưởng qua `WalletRepository.add_balance` trực tiếp (không gọi CurrencyService).
- **Bảng**: `guild_quest` (định nghĩa), `user_quest_progress` (tiến độ per user/quest/kỳ, unique `(quest_id,user_id,period_key)`).
- **Hot path**: ghi nhận earn_coins mỗi tin ăn coin = 1 SELECT (enabled earn quests, indexed) + UPDATE/quest. Chấp nhận v1.

REST CRUD: `GET/POST /guilds/{id}/quests`, `PATCH/DELETE /guilds/{id}/quests/{quest_id}` (gate `require_managed_guild`). PATCH là partial update (chỉ field gửi lên mới đổi).

---

## 5. Vận hành

- **Sau khi thêm migration mà stack đang chạy:** `docker compose exec api alembic upgrade head` (uvicorn `--reload` KHÔNG chạy migration). Quests migration: `f6a7b8c9d0e1`.
- **Giới hạn v1 (chấp nhận):** sửa target khi member đang làm → tính theo target mới; row kỳ cũ không dọn; quests vô dụng nếu currency tắt.
