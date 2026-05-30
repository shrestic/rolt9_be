# Mini-games — Hướng dẫn & Workflow

Ba trò cá cược coin: **coinflip**, **tài xỉu**, **nổ hũ**. Là sink tiêu coin (nhà cái ~5%) chống lạm phát.

---

## 1. Tính năng làm gì

- Member cược coin vào 3 trò may rủi. Thắng → nhận thưởng, thua → mất cược.
- **Nhà cái ~5%**: trung bình người chơi lỗ nhẹ → coin bị rút khỏi nền kinh tế (cân với việc kiếm coin từ chat/daily/quest).
- **Phụ thuộc:** Currency bật (cược/thưởng đều là coin).

---

## 2. Cho admin — Dashboard → server → Mini-games

| Trường | Ý nghĩa | Mặc định |
|---|---|---|
| **Enable** | Bật/tắt mini-games | off |
| **Min bet** | Cược tối thiểu | 10 |
| **Max bet** | Cược tối đa | 10.000 |

Nhà cái (~5%) cố định trong code, không chỉnh qua FE.

---

## 3. Cho member — lệnh Discord

| Lệnh | Việc |
|---|---|
| `/game flip <bet> <Ngửa\|Sấp>` | Tung đồng xu 50/50 → thắng ×1.9 |
| `/game taixiu <bet> <Tài\|Xỉu>` | Tổng 3 xúc xắc; Xỉu ≤10, Tài ≥11 → thắng ×1.9 |
| `/game slots <bet>` | Nổ hũ: 3 giống = jackpot ×10, 2 giống = ×1.6 |

- Cược phải trong khoảng min/max và ≤ số dư (else ❌).
- **Cooldown 3s/người/lệnh** (chống spam) → ⏳ nếu bấm nhanh.

Ví dụ: `🎲 4+5+2=11 (Tài) — 🎉 Thắng! +90 🪙 (số dư 1.290)` · `🎰 💎💎💎 — 🎉 Thắng! +900 🪙` · `🪙 Sấp — 😢 Thua 100 🪙 (số dư 900)`.

---

## 4. Cơ chế bên trong (cho dev)

```
/game flip → MinigameCog (cooldown 3s) → MinigameService._play
  ├─ enabled? bet ∈ [min,max]?
  ├─ WalletRepository.add_balance(-bet)   ← trừ cược; thiếu tiền → ValueError, KHÔNG chơi
  ├─ outcome = minigame_logic.play_*(rng, bet, choice)
  └─ thắng → add_balance(+payout)         ← cùng transaction
```

- **Logic thuần** `minigame_logic.py`: nhận `random.Random` bơm vào → test tất định (seed). Hệ số ~5% nhà cái (coinflip/taixiu ×1.9, slots ×10/×1.6 — EV ghi trong docstring).
- **Atomic & an toàn**: trừ cược TRƯỚC (guarded `add_balance`, không âm) → charge fail thì không chơi; credit thắng cùng transaction → không tạo/mất coin.
- **Cooldown**: `@app_commands.checks.cooldown(1, 3.0)` in-memory (reset khi bot restart) + `cog_app_command_error` render ⏳.
- **Decoupled**: MinigameService dùng `WalletRepository` trực tiếp (không gọi CurrencyService).
- **Không bảng per-user** — 1 ván chỉ là biến động ví. Config: `guild_minigame_config` (enabled, min_bet, max_bet).

REST: GET/PUT `/guilds/{id}/minigame/settings` (gate `require_managed_guild`).

---

## 5. Vận hành

- **Thêm migration lúc stack chạy:** `docker compose exec api alembic upgrade head`. Minigame migration: `c9d0e1f2a3b4`.
- **Giới hạn v1 (chấp nhận):** RNG `random.Random` (không cryptographic, đủ cho game vui); cooldown in-memory mất khi restart; nhà cái cố định ~5%.
