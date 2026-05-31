"""Probe: câu văn end-user (tiếng Việt) -> model chọn tool nào.

Chạy live qua gateway.complete_raw với FULL tool specs (gồm actions) trên 1 guild
đã cấu hình key, để xem model có map đúng ý người dùng sang đúng tool + args không.
KHÔNG thực thi action — chỉ in ra tool model định gọi.
"""

import asyncio
import sys

from app.db.session import session_scope
from app.repositories.agent_message import AgentMessageRepository
from app.repositories.ai_config import AIConfigRepository
from app.repositories.ai_usage import AIUsageRepository
from app.repositories.guild import GuildRepository
from app.repositories.memory_doc import MemoryDocRepository
from app.repositories.user_memory import UserMemoryRepository
from app.services.ai.agent_service import build_system
from app.services.ai.ai_gateway import AIGateway
from app.services.ai.provider import get_ai_provider
from app.services.ai.tools.registry import tool_specs

GUILD_DISCORD_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 1480247310813499412

# (mô tả, câu end-user, tool kỳ vọng)
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
    ("unban", "gỡ ban cho thằng BadGuy123 đi, nó hối lỗi rồi", "unban"),
    ("timeout/mute", "mute mồm thằng @ồn ào 15 phút", "timeout"),
    ("untimeout/unmute", "gỡ mute cho @Đạt đi nó im rồi", "untimeout"),
    ("server info", "server mình có bao nhiêu thành viên rồi nhỉ", "server_info"),
    ("giờ", "giờ là mấy giờ rồi bot", "current_time"),
    ("remember", "từ nay gọi @An là thằng loz nha bot", "remember"),
    ("chat thường (KHÔNG tool)", "chào bot hôm nay khỏe không", "(không gọi tool)"),
]


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
        # build_system cần các repo? Không — chỉ cần persona/facts/doc.
        _ = (AgentMessageRepository, UserMemoryRepository)  # giữ import gọn

        specs = tool_specs(has_search=bool(cfg.tools_enabled), include_actions=True)
        print(f"== Guild {GUILD_DISCORD_ID} | model={cfg.model} | {len(specs)} tools ==\n")

        ok = 0
        for desc, phrase, expected in CASES:
            system = build_system(cfg.persona or "", "", "Đạt", memory_doc, "")
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": phrase},
            ]
            try:
                res = await gateway.complete_raw(
                    guild_discord_id=GUILD_DISCORD_ID, messages=messages, tools=specs
                )
            except Exception as e:  # noqa: BLE001
                print(f"[LỖI] {desc!r}: {e}")
                continue
            if res.tool_calls:
                got = res.tool_calls[0]["name"]
                args = res.tool_calls[0]["arguments"]
            else:
                got = "(không gọi tool)"
                args = (res.text or "")[:60]
            hit = "✅" if got == expected else "❌"
            if got == expected:
                ok += 1
            print(f"{hit} [{desc}]")
            print(f"    câu : {phrase}")
            print(f"    chọn: {got}   (kỳ vọng: {expected})")
            print(f"    args: {args}\n")
        print(f"== Đúng {ok}/{len(CASES)} ==")


if __name__ == "__main__":
    asyncio.run(main())
