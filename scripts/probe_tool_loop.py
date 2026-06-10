"""Probe loop: runs the FULL tool-calling loop (<=4 steps) but with a FAKE execute -- does
not touch real Discord. Records the SEQUENCE of tools the model calls across steps, to see
whether it ultimately calls the right action tool (even if it calls server_info first)."""

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
    ("create role", "make me a role called VIP in red", "create_role"),
    ("assign role", "slap the VIP role on @Dat would ya", "assign_role"),
    ("remove role", "take the Mod role off @Dat", "remove_role"),
    ("delete role", "just nuke the VIP role from the server", "delete_role"),
    ("enable plugin", "turn on the leveling plugin for me", "toggle_plugin"),
    ("disable plugin", "kill the welcome thing, stop greeting people", "toggle_plugin"),
    ("enable currency", "fire up the currency economy system", "toggle_plugin"),
    ("kick", "kick @spammer outta the server for me", "kick"),
    ("ban", "ban @toxic for good", "ban"),
    ("ban (polite)", "hey @bot could you please ban @toxic", "ban"),
    ("unban", "unban BadGuy123, he's sorry now", "unban"),
    ("timeout/mute", "mute @noisy for 15 mins", "timeout"),
    ("untimeout/unmute", "unmute @Dat, he's quiet now", "untimeout"),
    ("server info", "how many members does our server have now", "server_info"),
    ("remember", "from now on call @An a dumbass, got it bot", "remember"),
]


def fake_execute(name: str, _args: dict) -> str:
    """Return a plausible fake result so the loop continues, WITHOUT touching Discord."""
    if name == "server_info":
        return "Roles: VIP, Mod, Member. Members: 42. Channels: general, chat."
    if name == "remember":
        return "Noted."
    if name == "current_time":
        return "2026-06-01 10:00 UTC"
    # action tools -> treat as staged successfully
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
        for desc, phrase, expected in CASES:
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
            print(f"{hit} [{desc}] phrase: {phrase}")
            print(f"    tool sequence: {seq or '(no tool called)'}   (need: {expected})")
            if not seq:
                print(f"    bot said     : {final_text}")
            print()
        print(f"== Right tool called (within <={MAX_STEPS} steps): {ok}/{len(CASES)} ==")


if __name__ == "__main__":
    asyncio.run(main())
