"""Probe: end-user English phrasing -> which tool does the model pick?

Runs live via gateway.complete_raw with the FULL tool specs (including actions) on a guild
that has a key configured, to see whether the model maps user intent to the right tool + args.
Does NOT execute the action -- only prints the tool the model intends to call.
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

# (description, end-user phrase, expected tool)
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
    ("unban", "unban BadGuy123, he's sorry now", "unban"),
    ("timeout/mute", "mute @noisy for 15 mins", "timeout"),
    ("untimeout/unmute", "unmute @Dat, he's quiet now", "untimeout"),
    ("server info", "how many members does our server have now", "server_info"),
    ("time", "hey bot what time is it", "current_time"),
    ("remember", "from now on call @An a dumbass, got it bot", "remember"),
    ("plain chat (NO tool)", "yo bot how's it going today", "(no tool call)"),
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
        # Does build_system need these repos? No -- it only needs persona/facts/doc.
        _ = (AgentMessageRepository, UserMemoryRepository)  # keep imports tidy

        specs = tool_specs(has_search=bool(cfg.tools_enabled), include_actions=True)
        print(f"== Guild {GUILD_DISCORD_ID} | model={cfg.model} | {len(specs)} tools ==\n")

        ok = 0
        for desc, phrase, expected in CASES:
            system = build_system(cfg.persona or "", "", "Dat", memory_doc, "")
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": phrase},
            ]
            try:
                res = await gateway.complete_raw(
                    guild_discord_id=GUILD_DISCORD_ID, messages=messages, tools=specs
                )
            except Exception as e:  # noqa: BLE001
                print(f"[ERROR] {desc!r}: {e}")
                continue
            if res.tool_calls:
                got = res.tool_calls[0]["name"]
                args = res.tool_calls[0]["arguments"]
            else:
                got = "(no tool call)"
                args = (res.text or "")[:60]
            hit = "✅" if got == expected else "❌"
            if got == expected:
                ok += 1
            print(f"{hit} [{desc}]")
            print(f"    phrase  : {phrase}")
            print(f"    picked  : {got}   (expected: {expected})")
            print(f"    args    : {args}\n")
        print(f"== Correct {ok}/{len(CASES)} ==")


if __name__ == "__main__":
    asyncio.run(main())
