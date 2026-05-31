"""Tool registry — schema + dispatch cho Claw Agent tools."""

import json
from dataclasses import dataclass, field

from app.services.ai.tools.current_time import run_current_time
from app.services.ai.tools.server_info import run_server_info
from app.services.ai.tools.web_search import run_web_search


@dataclass
class ToolContext:
    guild_snapshot: dict | None = None
    # Action context (sub-project 3) — chỉ dùng khi include_actions.
    can_act: bool = False
    pending: list = field(default_factory=list)
    role_names: list[str] = field(default_factory=list)
    target_user_ids: list[int] = field(default_factory=list)
    commander_id: int | None = None
    commander_perms: dict = field(default_factory=dict)
    guild_discord_id: int | None = None


_WEB_SEARCH_SPEC = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Tra thông tin mới/thực tế trên internet. Dùng khi cần dữ kiện ngoài kiến thức.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Truy vấn tìm kiếm"}},
            "required": ["query"],
        },
    },
}
_SERVER_INFO_SPEC = {
    "type": "function",
    "function": {
        "name": "server_info",
        "description": "Thông tin server Discord hiện tại.",
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["member_count", "roles", "channels"]}
            },
            "required": ["kind"],
        },
    },
}
_CURRENT_TIME_SPEC = {
    "type": "function",
    "function": {
        "name": "current_time",
        "description": "Giờ và ngày hiện tại (UTC).",
        "parameters": {"type": "object", "properties": {}},
    },
}


def tool_specs(has_search: bool, include_actions: bool = False) -> list[dict]:
    specs = [_SERVER_INFO_SPEC, _CURRENT_TIME_SPEC]
    if has_search:
        specs = [_WEB_SEARCH_SPEC, *specs]
    if include_actions:
        from app.services.ai.actions.registry import ACTION_SPECS  # lazy: tránh vòng import

        specs = [*specs, *ACTION_SPECS]
    return specs


def parse_args(raw: str | None) -> dict:
    try:
        return json.loads(raw or "{}")
    except (ValueError, TypeError):
        return {}


async def execute(name: str, args: dict, ctx: ToolContext) -> str:
    if name == "web_search":
        return await run_web_search(str(args.get("query", "")))
    if name == "server_info":
        return run_server_info(str(args.get("kind", "")), ctx.guild_snapshot)
    if name == "current_time":
        return run_current_time()
    # Action tools (sub-project 3): chỉ STAGE (validate), không thực thi ở đây.
    from app.services.ai.actions.registry import ACTION_PERMS, stage  # lazy

    if name in ACTION_PERMS:
        return await stage(name, args, ctx)
    return f"Tool không tồn tại: {name}"
