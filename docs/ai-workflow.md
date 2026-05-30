# AI Layer — Hướng dẫn & Workflow

Tầng nền AI (Claude) dùng chung + 4 feature: **Roast, Summarize, Q&A (Ask), Personality (Chat)**.

---

## 1. Tổng quan

- Bot gọi **Claude (Anthropic)** qua một **gateway dùng chung** (`AIGateway`).
- **Bot trả tiền** (key global `ANTHROPIC_API_KEY`). Mỗi server có **hạn mức token/tháng** để chặn chi phí.
- 4 feature đều cắm vào gateway: `/roast`, `/summarize`, `/ask`, `/chat`.

---

## 2. Cho admin — Dashboard → server → AI

| Trường | Ý nghĩa | Mặc định |
|---|---|---|
| **Enable AI** | Bật/tắt toàn bộ AI cho server | off |
| **Monthly token budget** | Trần token Claude/tháng (UTC). Hết → AI từ chối tới tháng sau | 100.000 |
| **Bot persona** | Cá tính cho `/chat` (rỗng = mặc định thân thiện) | "" |
| **Kho tri thức** | Danh sách FAQ (title + content) cho `/ask` — thêm/xóa ở dashboard | — |
| *(hiển thị)* | "Đã dùng X / Y token tháng này" | — |

**Vận hành:** cần đặt `ANTHROPIC_API_KEY` trong env của container `api`. Thiếu key → AI báo "chưa cấu hình" (không crash).

---

## 3. Cho member — lệnh Discord

| Lệnh | Việc |
|---|---|
| `/roast <member>` | AI cà khịa thành viên (lầy, không xúc phạm nặng). Cooldown 10s |
| `/summarize [count]` | Tóm tắt N tin gần nhất của kênh (mặc định 30, tối đa 100). Cooldown 15s |
| `/ask <câu hỏi>` | Trả lời dựa trên **kho tri thức** server admin nạp; ngoài kho → "chưa có thông tin". Cooldown 10s |
| `/chat <lời nhắn>` | Trò chuyện với bot theo **persona** của server. Cooldown 8s |

- AI tắt / thiếu key / hết quota tháng → ❌ thông báo nhẹ nhàng. Roast chặn bot/tự-roast.

---

## 4. Cơ chế bên trong (cho dev)

```
Feature (vd /roast) → RoastService → AIGateway.complete(guild, system, prompt)
   ├─ guild đăng ký? AI enabled? provider.available (có key)? quota tháng còn?
   ├─ provider.complete(...) → Claude (AnthropicAIProvider, import lazy)
   └─ ghi token (input+output) vào ai_usage tháng hiện tại
```

- **`AIProvider`** (provider.py): protocol; `AnthropicAIProvider` (thật, lazy import SDK) + `FakeAIProvider` (test, không gọi mạng). `get_ai_provider()` = singleton từ settings.
- **`AIGateway`**: chokepoint duy nhất — check **enabled + key + budget** trước khi tốn tiền, gọi provider, ghi token. Mọi feature AI cắm vào đây (decoupled, không gọi nhau).
- **Cost guard**: `guild_ai_config.monthly_token_budget` + `ai_usage` (token/tháng theo `period_key="YYYY-MM"`, atomic increment). Vượt → ValueError.
- **Config**: `ANTHROPIC_API_KEY`, `AI_MODEL` (default `claude-haiku-4-5-20251001` — rẻ), `AI_MAX_TOKENS` (default 400).
- **Bảng**: `guild_ai_config` (enabled, budget), `ai_usage` (token/tháng). Migration `d0e1f2a3b4c5`.
- **Test**: dùng `FakeAIProvider` → không gọi Claude thật, tất định.

REST: GET/PUT `/guilds/{id}/ai/settings` (kèm `tokens_used_this_month`), gate `require_managed_guild`.

---

## 5. Thêm feature AI mới (mẫu)

1. Viết `XxxService(gateway: AIGateway)` với system prompt riêng → gọi `gateway.complete(...)`.
2. Cog build gateway: `AIGateway(guild_repo, AIConfigRepository, AIUsageRepository, get_ai_provider())`.
3. Test bằng `FakeAIProvider`.

→ Summarizer / Q&A / Personality đều theo mẫu này.

---

## 6. Giới hạn chấp nhận (v1)

- Global key (BYO-key per-guild để v2); model cố định qua env; cooldown + budget chống đốt tiền; nội dung do LLM nên system prompt cấm xúc phạm nặng nhưng không tuyệt đối.
