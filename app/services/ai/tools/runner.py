"""ToolRunner — native function-calling loop for Claw Agent (≤ MAX_TOOL_STEPS steps)."""

from app.services.ai.tools.registry import ToolContext, execute, parse_args, tool_specs

MAX_TOOL_STEPS = 4


async def run_with_tools(
    *,
    gateway,
    guild_discord_id: int,
    system: str,
    history: list[dict],
    user_text: str,
    ctx: ToolContext,
    has_search: bool,
    include_actions: bool = False,
    now=None,
) -> str:
    messages = [
        {"role": "system", "content": system},
        *history,
        {"role": "user", "content": user_text},
    ]
    specs = tool_specs(has_search, include_actions=include_actions)
    for _ in range(MAX_TOOL_STEPS):
        res = await gateway.complete_raw(
            guild_discord_id=guild_discord_id, messages=messages, tools=specs, now=now
        )
        if not res.tool_calls:
            return res.text or "Sorry, I couldn't come up with an answer — try again."
        messages.append(res.raw_message)
        for call in res.tool_calls:
            result = await execute(call["name"], parse_args(call["arguments"]), ctx)
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
    # Hit the ceiling -> force an answer, no tools.
    final = await gateway.complete_raw(
        guild_discord_id=guild_discord_id, messages=messages, tools=None, now=now
    )
    return final.text or "I'm not done looking that up — try again."
