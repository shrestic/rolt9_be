"""Probe loop: chạy FULL vòng tool-calling (≤4 bước) nhưng execute GIẢ — không đụng
Discord thật. Ghi lại CHUỖI tool model gọi qua các bước, để xem cuối cùng nó có gọi
đúng tool hành động không (kể cả khi nó gọi server_info trước rồi mới hành động)."""

import asyncio
import sys

from app.db.session import session_scope
from app.repositories.ai_config import AIConfigRepository
from app.repositories.ai_usage import AIUsageRepository
from app.repositories.guild import GuildRepository
from app.repositories.memory_doc import MemoryDocRepository
from app.services.ai.agent_service import build_system
from app.services.ai.ai_gateway import AIGateway
from app.services.ai.provider import get_ai_provider
from app.services.ai.tools.registry import parse_args, tool_specs

GUILD_DISCORD_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 1480247310813499412
MAX_STEPS = 4

CASES = [
    ("tạo role", "tạo cho tao role tên VIP màu đỏ đi", "create_role"),
    ("gán role", "gán role VIP cho @Đạt với", "assign_role"),
    ("gỡ role", "gỡ cái role Mod của @Đạt ra", "remove_role"),
    ("xóa role", "xóa luôn role VIP khỏi server đi", "delete_role"),
    ("bật plugin", "bật cái plugin tính level lên cho tao", "toggle_plugin"),
    ("tắt plugin", "tắt welcome đi đừng chào nữa", "toggle_plugin"),
    ("bật currency", "mở hệ thống tiền tệ currency lên", "toggle_plugin"),
    ("kick", "kick thằng @spammer ra khỏi server giùm", "kick"),
    ("ban", "ban @toxic vĩnh viễn cho tao", "ban"),
    ("ban (lịch sự)", "@bot ơi ban giúp mình bạn @toxic nhé", "ban"),
    ("unban", "gỡ ban cho thằng BadGuy123 đi, nó hối lỗi rồi", "unban"),
    ("timeout/mute", "mute mồm thằng @ồn ào 15 phút", "timeout"),
    ("untimeout/unmute", "gỡ mute cho @Đạt đi nó im rồi", "untimeout"),
    ("server info", "server mình có bao nhiêu thành viên rồi nhỉ", "server_info"),
    ("remember", "từ nay gọi @An là thằng loz nha bot", "remember"),
]


def fake_execute(name: str, _args: dict) -> str:
    """Trả kết quả giả hợp lý để loop tiếp tục, KHÔNG đụng Discord."""
    if name == "server_info":
        return "Roles: VIP, Mod, Member. Thành viên: 42. Kênh: general, chat."
    if name == "remember":
        return "Đã ghi nhớ."
    if name == "current_time":
        return "2026-06-01 10:00 UTC"
    # action tools -> coi như đã stage thành công
    return f"Đã chuẩn bị hành động {name}. Chờ admin xác nhận/thực thi."


async def main():
    async with session_scope() as session:
        gateway = AIGateway(
            guild_repo=GuildRepository(session),
            config_repo=AIConfigRepository(session),
            usage_repo=AIUsageRepository(session),
            provider=get_ai_provider(),
        )
        guild = await GuildRepository(session).get_by_discord_id(GUILD_DISCORD_ID)
        cfg = await AIConfigRepository(session).get(guild.id)
        memory_doc = await MemoryDocRepository(session).get_doc(guild.id)
        specs = tool_specs(has_search=bool(cfg.tools_enabled), include_actions=True)

        ok = 0
        for desc, phrase, expected in CASES:
            system = build_system(cfg.persona or "", "", "Đạt", memory_doc, "")
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": phrase},
            ]
            seq = []
            final_text = ""
            for _ in range(MAX_STEPS):
                res = await gateway.complete_raw(
                    guild_discord_id=GUILD_DISCORD_ID, messages=messages, tools=specs
                )
                if not res.tool_calls:
                    final_text = (res.text or "")[:80]
                    break
                messages.append(res.raw_message)
                for call in res.tool_calls:
                    seq.append(call["name"])
                    result = fake_execute(call["name"], parse_args(call["arguments"]))
                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
            hit = "✅" if expected in seq else "❌"
            if expected in seq:
                ok += 1
            print(f"{hit} [{desc}] câu: {phrase}")
            print(f"    chuỗi tool: {seq or '(không gọi tool nào)'}   (cần: {expected})")
            if not seq:
                print(f"    bot nói   : {final_text}")
            print()
        print(f"== Gọi đúng tool (trong ≤{MAX_STEPS} bước): {ok}/{len(CASES)} ==")


if __name__ == "__main__":
    asyncio.run(main())
