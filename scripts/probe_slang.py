"""Probe slang: SLANG / AMBIGUOUS English phrases -> does the model understand & call the right tool?
Some phrases are ambiguous (boot = kick or ban?) so 'expected' is a SET of acceptable tools.
Runs the full loop (<=4 steps) with a fake execute (does not touch real Discord)."""

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

# (description, slang phrase, {acceptable tools})
CASES = [
    ("shut up = mute", "shut @kia up for a bit", {"timeout"}),
    ("zip it 5 min", "zip it on @noisy for 5 mins would ya", {"timeout"}),
    ("boot out = kick", "boot @toan out of here", {"kick"}),
    ("get outta sight = kick/ban", "get @toxic outta my sight for good", {"kick", "ban"}),
    ("lock out = ban", "lock @spam out permanently", {"ban"}),
    ("let back in = unban", "let BadGuy123 back in, poor guy", {"unban"}),
    ("give a voice back = unmute", "give @Dat his voice back, he's behaving now", {"untimeout"}),
    ("hand a rank = assign", "hand @An the VIP rank already", {"assign_role"}),
    ("strip the rank = remove", "strip the Mod rank off @An", {"remove_role"}),
    ("bonk = timeout", "bonk @toxic for 30 mins so he learns", {"timeout"}),
    ("trash role = delete", "trash that junk Newbie role", {"delete_role"}),
    ("spin up role = create", "spin up a role called Carry Squad for us", {"create_role"}),
    ("server busy? = info", "is the server packed today bot", {"server_info"}),
    ("jot down = remember", "jot this down: @Binh always misses deadlines", {"remember"}),
    ("turn on coin game", "fire up that coin currency game for fun", {"toggle_plugin"}),
    ("lock up = timeout", "lock @rowdy up for an hour", {"timeout"}),
    ("nuke = kick/ban", "nuke this troublemaker @disrupt for me", {"kick", "ban"}),
]


def fake_execute(name: str, _args: dict) -> str:
    if name == "server_info":
        return "Roles: VIP, Mod, Member, Newbie. Members: 42. Channels: general."
    if name == "remember":
        return "Noted."
    if name == "current_time":
        return "2026-06-01 10:00 UTC"
    return f"Staged action {name}. Waiting for admin confirmation/execution."


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
            system = build_system(cfg.persona or "", "", "Dat", memory_doc, "")
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
            print(f"    tool: {seq or '(no call)'}   (accepted: {accept})")
            if not seq:
                print(f"    bot said: {final_text}")
            print()
        print(f"== Understood correctly: {ok}/{len(CASES)} ==")


if __name__ == "__main__":
    asyncio.run(main())
