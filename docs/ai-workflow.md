# AI Layer — Hướng dẫn & Workflow

Tầng nền AI dùng chung + 4 feature: **Roast, Summarize, Q&A (Ask), Personality (Chat)**.

> **v2 (BYO-key đa provider — 2026-05-31):** mỗi server **tự nhập API key** của mình, **chọn provider/model** (Anthropic/OpenAI/Gemini/Groq qua **LiteLLM**), và budget tính bằng **USD/tháng** (không còn token). Migration `b4c5d6e7f8a9`. Xem mục 4. **Sau khi deploy v2, admin phải vào dashboard nhập lại API key + đặt lại budget** (đơn vị đổi token→USD, mặc định $5; AI tắt cho tới khi có key).

---

## 1. Tổng quan

- Bot gọi LLM qua một **gateway dùng chung** (`AIGateway`) → **LiteLLM** (gọi ~100 provider cùng format, tự tính cost USD).
- **Server tự trả tiền** bằng **API key riêng** (lưu mã hóa Fernet trong DB, không fallback key global). Mỗi server có **trần USD/tháng** để chặn chi phí.
- 4 feature đều cắm vào gateway: `/roast`, `/summarize`, `/ask`, `/chat` (chữ ký gateway không đổi giữa v1→v2).

---

## 2. Cho admin — Dashboard → server → AI

| Trường | Ý nghĩa | Mặc định |
|---|---|---|
| **Enable AI** | Bật/tắt toàn bộ AI cho server | off |
| **Provider** | Anthropic / OpenAI / Gemini / Groq (từ catalog) | "" |
| **Model** | Model thuộc provider đã chọn (vd `claude-haiku-4-5`, `gpt-4o-mini`) | "" |
| **API key** | Key của server, mã hóa Fernet. GET chỉ trả `has_key` + 4 ký tự cuối; không bao giờ lộ key. Để trống = giữ key cũ, gửi "" = xóa | — |
| **Budget USD/tháng** | Trần chi phí USD/tháng (UTC). Vượt → AI từ chối tới tháng sau | 5.0 |
| **Bot persona** | Cá tính cho `/chat` (rỗng = mặc định thân thiện) | "" |
| **Kho tri thức** | Danh sách FAQ (title + content) cho `/ask` — thêm/xóa ở dashboard | — |
| *(hiển thị)* | "Tháng này: X token ≈ $Y / $Z budget" | — |

**Vận hành:** thiếu key/provider/model → AI báo "chưa cấu hình" (không crash). `ANTHROPIC_API_KEY` global đã **deprecated** (không còn là đường chính, gateway không fallback). `TOKEN_ENCRYPTION_KEY` phải set để mã hóa key guild.

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
   ├─ guild đăng ký? AI enabled? có api_key_enc + provider + model? cost USD tháng < budget?
   ├─ decrypt_str(api_key_enc) → provider.complete(provider, model, api_key, ...) → LiteLLM
   └─ ghi token (input+output) + cost_usd vào ai_usage tháng hiện tại
```

- **`AIProvider`** (provider.py): protocol stateless — `complete(*, provider, model, api_key, system, prompt, max_tokens)`. `LiteLLMProvider` (thật, lazy import `litellm`, dùng `litellm.acompletion` + `litellm.completion_cost`; cost lỗi → 0.0 + log, không crash) + `FakeAIProvider` (test, không gọi mạng, trả cost giả). `get_ai_provider()` = singleton `LiteLLMProvider()` (stateless nên share an toàn; key/model truyền per-call).
- **`AIGateway`**: chokepoint duy nhất — check **enabled + (key/provider/model) + budget USD** trước khi tốn tiền, giải mã key, gọi provider, ghi token + cost. Mọi feature AI cắm vào đây (decoupled, không gọi nhau).
- **Catalog** (`catalog.py`): whitelist `AI_CATALOG` + `is_valid(provider, model)`. Nguồn sự thật duy nhất: validate PUT settings + feed endpoint `/ai/catalog` cho FE.
- **Cost guard**: `guild_ai_config.monthly_budget_usd` (Numeric) + `ai_usage.cost_usd` (Numeric, atomic increment cùng `tokens`, theo `period_key="YYYY-MM"`). `cost_this_period >= budget` → ValueError.
- **Key**: `guild_ai_config.api_key_enc` (LargeBinary, Fernet qua `app/core/crypto.py`). NULL = chưa nhập. API không bao giờ trả key (chỉ `has_key` + `key_hint` 4 ký tự cuối).
- **Config**: `AI_MAX_TOKENS` (default 400) vẫn dùng. `AI_MODEL` chỉ là default tham khảo. `ANTHROPIC_API_KEY` **deprecated** (không fallback). `TOKEN_ENCRYPTION_KEY` bắt buộc.
- **Bảng**: `guild_ai_config` (enabled, provider, model, api_key_enc, monthly_budget_usd, persona), `ai_usage` (tokens + cost_usd/tháng). Migration v1 `d0e1f2a3b4c5`, v2 BYO-key `b4c5d6e7f8a9`.
- **Test**: dùng `FakeAIProvider` → không gọi mạng, tất định; `LiteLLMProvider` test bằng mock `sys.modules["litellm"]`.

REST: GET/PUT `/guilds/{id}/ai/settings` (kèm `has_key`/`key_hint`/`tokens_used_this_month`/`cost_used_this_month`), GET `/ai/catalog` (không cần guild_id), gate `require_managed_guild` (catalog miễn gate + miễn X-Client-ID).

---

## 5. Thêm feature AI mới (mẫu)

1. Viết `XxxService(gateway: AIGateway)` với system prompt riêng → gọi `gateway.complete(...)`.
2. Cog build gateway: `AIGateway(guild_repo, AIConfigRepository, AIUsageRepository, get_ai_provider())`.
3. Test bằng `FakeAIProvider`.

→ Summarizer / Q&A / Personality đều theo mẫu này.

---

## 6. Giới hạn chấp nhận (v2)

- **BYO-key per-guild** (server tự trả tiền); provider/model từ **catalog tĩnh** (thêm model mới = sửa `catalog.py`); budget USD là hàng rào **mềm** (request cuối có thể lố chút vì cost biết sau khi gọi); cost dựa bảng giá LiteLLM (model lạ → cost 0 + log); key sai/hết hạn → LiteLLM raise, không ghi cost. cooldown + budget chống đốt tiền; nội dung do LLM nên system prompt cấm xúc phạm nặng nhưng không tuyệt đối.
- **Phi mục tiêu v2:** LiteLLM Proxy riêng, streaming, load-balance nhiều key, lịch sử hội thoại.
