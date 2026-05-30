# Welcome — Hướng dẫn & Workflow

Tin nhắn **chào mừng** thành viên mới (`on_member_join`) và **tạm biệt** khi rời server
(`on_member_remove`). Hỗ trợ template tĩnh (placeholder) + lời chào do **AI** sinh (tùy chọn).

---

## 1. Tổng quan

- Thành viên **join** → bot render template (hoặc nhờ AI) → đăng vào **kênh đã cấu hình**.
- Thành viên **leave** → bot đăng template tạm biệt (tĩnh, không AI) vào cùng kênh.
- Tất cả tắt theo mặc định; admin bật + chọn kênh ở dashboard.

---

## 2. Cho admin — Dashboard → server → Welcome

| Trường | Ý nghĩa | Mặc định |
|---|---|---|
| **Enable welcome** | Bật/tắt tin chào mừng khi có người vào | off |
| **Channel** | Kênh đăng cả tin chào mừng lẫn tạm biệt | — (bắt buộc khi bật) |
| **Welcome template** | Mẫu tin chào mừng (dùng placeholder bên dưới) | "Chào mừng {user} đến với {server}! 🎉 Bạn là thành viên thứ {count}." |
| **AI-generated welcome** | Nhờ Claude viết lời chào (vẫn @mention member); lỗi/hết quota → tự fallback về template | off |
| **Enable leave message** | Bật/tắt tin tạm biệt khi có người rời | off |
| **Leave template** | Mẫu tin tạm biệt (tĩnh, không AI) | "{user} đã rời khỏi **{server}**. 👋" |

**Placeholder** (thay bằng `str.replace`, không phải `format` — nên ký tự `{}` thường trong text không gây lỗi):

| Placeholder | Thay bằng |
|---|---|
| `{user}` | Mention/tên thành viên |
| `{server}` | Tên server |
| `{count}` | Số thành viên hiện tại |

**Vận hành:**
- Cần bật **privileged intent `Server Members`** ở Discord Developer Portal (bot đã khai `intents.members = True`).
- AI welcome dùng chung `AIGateway` (xem [ai-workflow](ai-workflow.md)) — cần `ANTHROPIC_API_KEY` + còn quota tháng; thiếu → tự fallback template.

---

## 3. Cơ chế bên trong (cho dev)

```
on_member_join → WelcomeCog → WelcomeService.build_welcome(...)
   ├─ config.enabled? có channel_id? (không → return None, bỏ qua)
   ├─ render_template(welcome_template, user/server/count)
   ├─ nếu ai_welcome: gateway.complete(WELCOME_SYSTEM, prompt) → prefix mention
   │     └─ ValueError (tắt/thiếu key/hết quota) → fallback text template
   └─ return (channel_id, text) → cog post qua discord_io (nuốt DiscordError)

on_member_remove → WelcomeCog → WelcomeService.build_leave(...)  # tĩnh, không AI
```

- **`render_template`** (`services/welcome/template.py`): thuần str.replace, không I/O — dễ test.
- **`WelcomeService`** (`services/welcome/welcome_service.py`): phụ thuộc `guild_repo`, `config_repo`, `gateway`. `build_welcome`/`build_leave` trả `tuple[int, str] | None` (None = không đăng). AI lỗi → nuốt, fallback template (không bao giờ làm hỏng sự kiện join).
- **`WelcomeCog`** (`bot/cogs/welcome.py`): listener mỏng; `_post` nuốt `DiscordError` để kênh sai/thiếu quyền không vỡ event.
- **Config table**: `guild_welcome_config` (guild_id PK, enabled, channel_id BigInteger nullable, welcome_template, ai_welcome, leave_enabled, leave_template). Repo theo mẫu no-404: `get`/`get_or_create`/`upsert`. Migration `a3b4c5d6e7f8`.
- **Test**: `FakeAIProvider` cho nhánh AI → không gọi mạng, tất định.

REST: GET/PUT `/guilds/{id}/welcome/settings`, gate `require_managed_guild`. `channel_id` là **string snowflake** trên wire, coerce int↔str ở biên endpoint.

---

## 4. Giới hạn chấp nhận (v1)

- Một kênh chung cho cả join lẫn leave (chưa tách); leave luôn tĩnh (không AI) để tiết kiệm token; không có ảnh/banner chào mừng (text-only); placeholder cố định (`{user}/{server}/{count}`).
