"""ToolRunner — vòng lặp native function-calling cho Claw Agent (≤ MAX_TOOL_STEPS bước)."""

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
    now=None,
) -> str:
    messages = [
        {"role": "system", "content": system},
        *history,
        {"role": "user", "content": user_text},
    ]
    specs = tool_specs(has_search)
    for _ in range(MAX_TOOL_STEPS):
        res = await gateway.complete_raw(
            guild_discord_id=guild_discord_id, messages=messages, tools=specs, now=now
        )
        if not res.tool_calls:
            return res.text
        messages.append(res.raw_message)
        for call in res.tool_calls:
            result = await execute(call["name"], parse_args(call["arguments"]), ctx)
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
    # Chạm trần -> buộc trả lời, không tool.
    final = await gateway.complete_raw(
        guild_discord_id=guild_discord_id, messages=messages, tools=None, now=now
    )
    return final.text or "Mình chưa tra xong, thử lại nhé."
