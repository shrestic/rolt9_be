"""Tool registry — schema + dispatch cho Claw Agent tools."""

import json
from dataclasses import dataclass

from app.services.ai.tools.current_time import run_current_time
from app.services.ai.tools.server_info import run_server_info
from app.services.ai.tools.web_search import run_web_search


@dataclass
class ToolContext:
    guild_snapshot: dict | None = None


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


def tool_specs(has_search: bool) -> list[dict]:
    specs = [_SERVER_INFO_SPEC, _CURRENT_TIME_SPEC]
    if has_search:
        specs = [_WEB_SEARCH_SPEC, *specs]
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
    return f"Tool không tồn tại: {name}"
