"""Probe slang: câu LÓNG / MƠ HỒ tiếng Việt -> model có hiểu & gọi đúng tool không.
Một số câu mơ hồ (tống cổ = kick hay ban?) nên 'expected' là TẬP tool chấp nhận được.
Chạy full loop ≤4 bước, execute giả (không đụng Discord thật)."""

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

# (mô tả, câu lóng, {tool chấp nhận được})
CASES = [
    ("im mồm = mute", "cho thằng @kia im mồm đi", {"timeout"}),
    ("câm 5 phút", "câm mồm thằng @ồn lại 5 phút giùm", {"timeout"}),
    ("đuổi cổ = kick", "đuổi cổ thằng @toàn ra ngoài", {"kick"}),
    ("tống cổ = kick/ban", "tống cổ @toxic đi cho khuất mắt tao", {"kick", "ban"}),
    ("cấm cửa = ban", "cấm cửa vĩnh viễn thằng @spam này", {"ban"}),
    ("thả ra = unban", "thả thằng BadGuy123 ra đi, tội nó", {"unban"}),
    ("mở mồm lại = unmute", "mở mồm cho @Đạt lại đi nó ngoan rồi", {"untimeout"}),
    ("phong chức = assign", "phong cho @An lên làm VIP đi", {"assign_role"}),
    ("tước chức = remove", "tước cái chức Mod của thằng @An đi", {"remove_role"}),
    ("bonk = timeout", "bonk thằng @toxic 30 phút cho chừa", {"timeout"}),
    ("dẹp role = delete", "dẹp cái role rác Newbie kia đi", {"delete_role"}),
    ("đẻ role = create", "đẻ cho anh em cái role tên Gánh Team", {"create_role"}),
    ("server đông ko = info", "nay server đông người ko bot", {"server_info"}),
    ("ghi lóng = remember", "ghi giùm: thằng @Bình hay đi trễ deadline", {"remember"}),
    ("bật game xu", "bật cái trò kiếm xu currency lên cho vui", {"toggle_plugin"}),
    ("nhốt = timeout", "nhốt thằng @quậy lại 1 tiếng", {"timeout"}),
    ("trảm = kick/ban", "trảm thằng @phá đám này giùm cái", {"kick", "ban"}),
]


def fake_execute(name: str, _args: dict) -> str:
    if name == "server_info":
        return "Roles: VIP, Mod, Member, Newbie. Thành viên: 42. Kênh: general."
    if name == "remember":
        return "Đã ghi nhớ."
    if name == "current_time":
        return "2026-06-01 10:00 UTC"
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
        for desc, phrase, accept in CASES:
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
                    final_text = (res.text or "")[:90]
                    break
                messages.append(res.raw_message)
                for call in res.tool_calls:
                    seq.append(call["name"])
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": fake_execute(call["name"], parse_args(call["arguments"])),
                        }
                    )
            hit = "✅" if any(e in seq for e in accept) else "❌"
            if any(e in seq for e in accept):
                ok += 1
            print(f"{hit} [{desc}] “{phrase}”")
            print(f"    tool: {seq or '(không gọi)'}   (chấp nhận: {accept})")
            if not seq:
                print(f"    bot nói: {final_text}")
            print()
        print(f"== Hiểu đúng: {ok}/{len(CASES)} ==")


if __name__ == "__main__":
    asyncio.run(main())
