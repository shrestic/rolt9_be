"""Tool registry — schema + dispatch cho Claw Agent tools."""

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.services.ai.tools.current_time import run_current_time
from app.services.ai.tools.server_info import run_server_info
from app.services.ai.tools.web_search import run_web_search

log = logging.getLogger(__name__)

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")  # mọi thời điểm người dùng nói là giờ VN


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
    # Server memory doc (OpenClaw-style) — tool `remember` ghi vào đây.
    memory_repo_doc: object | None = None
    guild_pk: object | None = None
    # Reminder (báo thức) — tool `remind` ghi vào đây; channel_id = kênh sẽ nhắc.
    reminder_repo: object | None = None
    channel_id: int | None = None


_REMEMBER_SPEC = {
    "type": "function",
    "function": {
        "name": "remember",
        "description": (
            "Ghi nhớ BỀN VỮNG một điều về server hoặc một người (biệt danh, tính cách, "
            "cách nói, luật, sở thích) để dùng lâu dài về sau. Gọi khi người dùng bảo "
            "'nhớ...', 'từ nay gọi X là...', hoặc khi học được điều đáng nhớ. "
            "Vì ghi chú nằm trong trí nhớ DÙNG CHUNG của server, khi ghi về người đang nói "
            "(tao/tôi/mình) hãy dùng TÊN THẬT của họ trong note (vd 'Phong muốn được gọi là ...') "
            "chứ ĐỪNG ghi 'user này'/'người này' — để sau đọc lại còn biết là ai."
        ),
        "parameters": {
            "type": "object",
            "properties": {"note": {"type": "string", "description": "Điều cần nhớ, ngắn gọn"}},
            "required": ["note"],
        },
    },
}
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
_CREATE_POLL_SPEC = {
    "type": "function",
    "function": {
        "name": "create_poll",
        "description": (
            "Tạo một cuộc bình chọn (poll) Discord thật trong kênh. Gọi khi người dùng muốn "
            "'tạo poll', 'vote', 'bình chọn', 'khảo sát'. Tự tách câu hỏi + các lựa chọn."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Câu hỏi của poll"},
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Các lựa chọn (2-10 cái)",
                },
                "duration_hours": {
                    "type": "integer",
                    "description": "Số giờ poll mở (mặc định 24, tối đa 168 = 7 ngày)",
                },
                "multiple": {
                    "type": "boolean",
                    "description": "Cho chọn nhiều đáp án không (mặc định false)",
                },
            },
            "required": ["question", "options"],
        },
    },
}


_REMIND_SPEC = {
    "type": "function",
    "function": {
        "name": "remind",
        "description": (
            "Đặt lời nhắc / báo thức cho TƯƠNG LAI. Gọi khi người dùng nói 'nhắc tao...', "
            "'hẹn...', 'báo thức...', 'tới giờ X nhắc...'. Tự tính thời điểm TUYỆT ĐỐI dựa vào "
            "'Bây giờ (giờ VN)' ĐÃ CHO SẴN trong prompt — ĐỪNG gọi current_time, cứ tính thẳng từ đó "
            "(vd 'ngày mai 5h30 chiều', 'thứ 7 tuần sau 8h', '2 tiếng nữa'). "
            "Người được @ trong tin sẽ được nhắc cùng (không @ ai thì nhắc người ra lệnh)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "when": {
                    "type": "string",
                    "description": "Thời điểm nhắc, định dạng 'YYYY-MM-DD HH:MM' theo GIỜ VN (24h)",
                },
                "message": {"type": "string", "description": "Nội dung cần nhắc"},
            },
            "required": ["when", "message"],
        },
    },
}


def tool_specs(has_search: bool, include_actions: bool = False) -> list[dict]:
    specs = [_REMEMBER_SPEC, _REMIND_SPEC, _CREATE_POLL_SPEC, _SERVER_INFO_SPEC, _CURRENT_TIME_SPEC]
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


def _parse_vn_to_utc(when_raw: str) -> datetime | None:
    """Chuỗi giờ VN (model tính ra) -> datetime UTC tz-aware. None nếu không parse được."""
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            naive = datetime.strptime(when_raw, fmt)
            return naive.replace(tzinfo=VN_TZ).astimezone(UTC)
        except ValueError:
            continue
    try:  # dự phòng: ISO bất kỳ
        dt = datetime.fromisoformat(when_raw)
        return (dt.replace(tzinfo=VN_TZ) if dt.tzinfo is None else dt).astimezone(UTC)
    except ValueError:
        return None


async def _create_reminder(args: dict, ctx: ToolContext) -> str:
    """Ghi 1 lời nhắc vào DB (qua ctx.reminder_repo). Model đã tính 'when' theo giờ VN."""
    if ctx.reminder_repo is None or ctx.guild_pk is None or ctx.channel_id is None:
        return "Chưa đặt được nhắc (thiếu ngữ cảnh)."
    when_raw = str(args.get("when", "")).strip()
    message = str(args.get("message", "")).strip()
    if not when_raw or not message:
        return "Cần cả thời điểm lẫn nội dung nhắc."
    remind_at = _parse_vn_to_utc(when_raw)
    if remind_at is None:
        return "Mình không hiểu thời điểm — cho dạng 'YYYY-MM-DD HH:MM' (giờ VN) nhé."
    if remind_at <= datetime.now(UTC):
        return "Thời điểm đó qua mất rồi, chọn lúc trong tương lai đi."
    targets = list(ctx.target_user_ids) or ([ctx.commander_id] if ctx.commander_id else [])
    await ctx.reminder_repo.create(
        guild_id=ctx.guild_pk,
        channel_id=ctx.channel_id,
        creator_id=ctx.commander_id or 0,
        target_ids=targets,
        message=message,
        remind_at=remind_at,
    )
    return f"Đã đặt nhắc lúc {when_raw} (giờ VN): {message}"


def _stage_poll(args: dict, ctx: ToolContext) -> str:
    """Validate args poll rồi xếp vào ctx.pending để cog gửi poll Discord thật vào kênh."""
    from app.services.ai.actions.registry import PendingAction  # lazy: tránh vòng import

    question = str(args.get("question", "")).strip()
    options = [str(o).strip() for o in (args.get("options") or []) if str(o).strip()]
    if not question:
        return "Thiếu câu hỏi cho poll."
    if not (2 <= len(options) <= 10):
        return "Poll cần 2-10 lựa chọn."
    dur = args.get("duration_hours")
    dur = dur if isinstance(dur, int) and 1 <= dur <= 168 else 24  # 1h..7 ngày, mặc định 24h
    ctx.pending.append(
        PendingAction(
            "create_poll",
            False,  # tạo poll không phải hành động phá -> không cần nút xác nhận
            f"Poll: {question}",
            {
                "question": question,
                "options": options,
                "duration_hours": dur,
                "multiple": bool(args.get("multiple")),
            },
        )
    )
    return f"Đã tạo poll: {question} ({len(options)} lựa chọn)."


async def execute(name: str, args: dict, ctx: ToolContext) -> str:
    log.info("agent tool call: name=%s args=%s", name, args)
    if name == "remember":
        note = str(args.get("note", ""))
        if ctx.memory_repo_doc is not None and ctx.guild_pk is not None and note.strip():
            await ctx.memory_repo_doc.append_note(ctx.guild_pk, note)
            return "Đã ghi nhớ."
        return "Chưa ghi nhớ được."
    if name == "remind":
        return await _create_reminder(args, ctx)
    if name == "create_poll":
        return _stage_poll(args, ctx)
    if name == "web_search":
        return await run_web_search(str(args.get("query", "")))
    if name == "server_info":
        return run_server_info(str(args.get("kind", "")), ctx.guild_snapshot)
    if name == "current_time":
        return run_current_time()
    # Action tools (sub-project 3): chỉ STAGE (validate) + xếp vào ctx.pending; cog execute sau.
    from app.services.ai.actions.registry import ACTION_PERMS, stage  # lazy

    if name in ACTION_PERMS:
        res = await stage(name, args, ctx)
        if isinstance(res, str):
            log.info("agent action stage rejected: name=%s -> %s", name, res)
            return res  # lỗi/từ chối -> báo lại model
        ctx.pending.append(res)
        log.info("agent action staged: name=%s desc=%s", name, res.description)
        return f"Đã chuẩn bị: {res.description}. Chờ admin xác nhận/thực thi."
    log.info("agent tool called: name=%s", name)
    return f"Tool không tồn tại: {name}"
