# Karma — Hướng dẫn & Workflow

Điểm uy tín do cộng đồng bình chọn (peer-rated). Member trao karma cho nhau bằng `/karma give @user`.

---

## 1. Tính năng làm gì

- Member trao **+1 karma** cho người khác qua `/karma give @user` để ghi nhận đóng góp/giúp đỡ.
- **Chỉ cộng** (không có downvote) — giữ không khí tích cực.
- **Cooldown theo cặp 24h**: mỗi người chỉ +1 cho **cùng một người** 1 lần/24h (vẫn khen người khác thoải mái).
- Chặn tự khen mình + chặn khen bot.
- **Thuần danh tiếng** — karma không đổi ra coin/badge; giá trị là uy tín + bảng xếp hạng.
- Độc lập, không cần currency/leveling.

---

## 2. Cho admin — Dashboard → server → Karma

- **Enable karma**: bật/tắt (mặc định tắt).
- Xem **bảng xếp hạng** karma (top member).

(Không có con số nào để chỉnh — karma chỉ là +1/lần, cooldown 24h cố định.)

---

## 3. Cho member — lệnh Discord

| Lệnh | Việc |
|---|---|
| `/karma give <member>` | Trao +1 karma. Chặn bot/tự-khen → ❌. Đã khen người đó <24h → ❌ |
| `/karma view [member]` | Xem điểm karma + hạng của mình/người khác |
| `/karma top` | Bảng xếp hạng 10 người karma cao nhất |

---

## 4. Cơ chế bên trong (cho dev)

```
/karma give @X → KarmaCog (chặn bot + self) → KarmaService.give
  ├─ config bật? giver≠receiver?
  ├─ KarmaGrantRepository.try_grant(giver, receiver, now, now-24h)  ← atomic; thất bại → ValueError (KHÔNG cộng điểm)
  └─ KarmaRepository.add_point(receiver)  ← atomic points+1
```

- **Atomic**: `try_grant` là guarded UPDATE (cooldown theo cặp trong WHERE) → không lách/không double-grant; `add_point` cộng dồn trong SQL → không lost-update.
- **Thứ tự an toàn**: claim cooldown TRƯỚC, fail thì raise ngay → grant bị chặn không bao giờ cộng điểm.
- **Decoupled**: KarmaService chỉ đọc qua repos, không gọi service khác.
- **Bảng**: `guild_karma_config` (toggle), `user_karma` (điểm nhận, index `(guild_id,points)` cho BXH), `karma_grant` (sổ cooldown theo cặp giver→receiver).
- **BXH**: points DESC, tie-break user_id ASC; `rank_of` = số người điểm cao hơn + 1. user_id ra dây dạng string (snowflake).

REST: GET/PUT `/guilds/{id}/karma/settings`, GET `/guilds/{id}/karma/leaderboard?page&page_size` (gate `require_managed_guild`).

---

## 5. Vận hành

- **Thêm migration lúc stack chạy:** `docker compose exec api alembic upgrade head` (uvicorn --reload không chạy migration). Karma migration: `b8c9d0e1f2a3`.
- **Giới hạn v1 (chấp nhận):** chỉ cộng (không gỡ); alt-farming chỉ chặn theo cặp (karma không reward nên động cơ thấp); sổ `karma_grant` không dọn (mỗi cặp 1 row).
