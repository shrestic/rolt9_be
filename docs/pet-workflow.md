# Server Pet — Hướng dẫn & Workflow

Mỗi server nuôi **một con pet chung** (Tamagotchi tập thể). Cả cộng đồng cùng cho ăn / chơi để giữ pet no & vui và nuôi nó lớn lên.

---

## 1. Tính năng làm gì

- **1 pet/server**, ai cũng góp tay nuôi.
- 2 chỉ số **No (hunger)** + **Vui (happiness)**, mỗi cái 0–100, **tự tụt theo thời gian**.
- **Cho ăn** (tốn coin) → +No. **Chơi** (miễn phí, cooldown 1h/người) → +Vui.
- Mỗi lần chăm → pet +XP → **lên level → tiến hóa** (🥚 Trứng → 🐣 Non → 🐤 Nhỡ → 🦅 Trưởng thành).
- Bỏ bê → thanh tụt về 0, pet hiện mặt buồn 😿 nhưng **không chết** — chăm lại là hồi.
- **Thuần cảm xúc/khoe** — pet không cho buff; niềm vui là cùng nuôi lớn.

> **Phụ thuộc:** Currency bật (cho ăn tốn coin). Chơi vẫn được khi currency tắt.

---

## 2. Cho admin — Dashboard → server → Pet

| Trường | Ý nghĩa | Mặc định |
|---|---|---|
| **Enabled** | Bật/tắt pet | off |
| **Name** | Tên pet (1–32 ký tự) | "Pet" |
| **Feed cost** | Coin mỗi lần cho ăn | 10 |
| **Feed amount** | +No mỗi lần ăn (1–100) | 30 |
| **Play amount** | +Vui mỗi lần chơi (1–100) | 30 |
| **Decay per day** | Mỗi thanh tụt /ngày (0–100) | 20 |

Decay 20/ngày nghĩa là thanh đầy (100) sẽ về 0 sau ~5 ngày không ai chăm.

---

## 3. Cho member — lệnh Discord

| Lệnh | Việc |
|---|---|
| `/pet status` | Xem pet: emoji giai đoạn + tâm trạng, 2 thanh No/Vui, level |
| `/pet feed` | Cho ăn (tốn coin) → +No. Thiếu coin → ❌ |
| `/pet play` | Chơi (miễn phí, đợi 1h giữa các lần) → +Vui |

Lên level / tiến hóa sẽ được báo ngay trong reply feed/play: "🎉 lên Lv X" / "✨ tiến hóa thành …".

---

## 4. Cơ chế bên trong (cho dev)

```
/pet feed → PetCog → PetService.feed
  ├─ settle decay (theo giờ từ last_decay_at, sàn 0)
  ├─ WalletRepository.add_balance(-feed_cost)   ← thiếu tiền → ValueError, KHÔNG đổi thanh
  ├─ hunger = min(100, hunger + feed_amount); xp += 5
  └─ save_state(..., last_decay_at=now)

/pet play → cooldown 1h (PetCooldownRepository.try_play, atomic) → settle → +Vui → save

/pet status / REST GET status → settle (TÍNH, không ghi) → trả về
```

- **Decay lazy**: tính lúc đọc/tương tác, **không có job nền**. `last_decay_at` chỉ advance khi feed/play; read luôn tính tương đối từ nó → hiển thị luôn đúng, GET không ghi (không side-effect).
- **Atomic**: `try_play` là guarded UPDATE (cooldown trong WHERE) → không lách được cooldown; feed trừ coin qua guarded `add_balance` → không âm.
- **An toàn**: trừ coin TRƯỚC khi cộng No → charge fail thì thanh không tăng. Cả hai trong cùng transaction (`session_scope`) → rollback chung.
- **Decoupled**: PetService đọc qua repos, trừ coin qua `WalletRepository` trực tiếp (không gọi CurrencyService).
- **Level/stage thuần**: `pet_logic.pet_level(xp)` (50 XP/level), `stage_for(level)` (mốc 1/5/15/30), `mood_for` (avg 70/40/10).
- **Bảng**: `guild_pet` (state+config, 1 row/guild), `user_pet_cooldown` (cooldown chơi per-user).

REST: GET/PUT `/guilds/{id}/pet/settings`, GET `/guilds/{id}/pet/status` (gate `require_managed_guild`).

---

## 5. Vận hành

- **Thêm migration lúc stack đang chạy:** `docker compose exec api alembic upgrade head` (uvicorn --reload KHÔNG chạy migration). Pet migration: `a7b8c9d0e1f2`.
- **Giới hạn v1 (chấp nhận):** pet không chết; không buff (không lỗ hổng farm); decay tính lazy; alt-farm play vô hại (không reward).
