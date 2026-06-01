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
    # Subscription (đăng ký nhận tin định kỳ) — tool `subscribe`/`unsubscribe`/`list_subscriptions`.
    subscription_repo: object | None = None


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


_LIST_REMINDERS_SPEC = {
    "type": "function",
    "function": {
        "name": "list_reminders",
        "description": (
            "Liệt kê các lời nhắc (báo thức) ĐANG CHỜ của người ra lệnh, kèm giờ + nội dung. "
            "Gọi khi user hỏi 'tao có nhắc gì', hoặc khi họ muốn xoá mà chưa rõ cái nào (cho họ xem để chọn)."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}
_CANCEL_REMINDER_SPEC = {
    "type": "function",
    "function": {
        "name": "cancel_reminder",
        "description": (
            "Huỷ / xoá lời nhắc (báo thức) đã đặt. Gọi khi user nói 'xoá nhắc...', 'huỷ báo thức...'. "
            "'query' = từ khoá trong nội dung hoặc giờ để tìm đúng cái (vd 'chơi game', '7h tối'). "
            "Nếu NHIỀU lời nhắc cùng khớp, tool sẽ trả về danh sách để bạn hỏi lại user cho rõ — "
            "ĐỪNG đoán bừa. Đặt 'all'=true CHỈ khi user nói rõ muốn xoá HẾT. Chỉ huỷ nhắc của chính họ."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Từ khoá nội dung/giờ để tìm (tuỳ chọn)",
                },
                "all": {"type": "boolean", "description": "true = huỷ TẤT CẢ nhắc của người đó"},
            },
        },
    },
}
_EDIT_REMINDER_SPEC = {
    "type": "function",
    "function": {
        "name": "edit_reminder",
        "description": (
            "Sửa lời nhắc đã đặt: đổi GIỜ và/hoặc NỘI DUNG. Gọi khi user nói 'dời nhắc ... sang ...', "
            "'đổi giờ nhắc ...', 'sửa nhắc ... thành ...', 'chuyển nhắc ... sang ...'. Khi user đã nêu RÕ "
            "lời nhắc nào + giá trị mới, GỌI THẲNG tool này (query=từ khoá cũ, when/message=giá trị mới), "
            "ĐỪNG gọi list_reminders trước. 'query' tìm theo nội dung HOẶC giờ cũ; nhiều cái khớp thì tool "
            "tự trả danh sách để hỏi lại. 'when'='YYYY-MM-DD HH:MM' (giờ VN), 'message'=nội dung mới. "
            "Cần ít nhất một trong when/message."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Từ khoá tìm lời nhắc cần sửa"},
                "when": {"type": "string", "description": "Giờ mới 'YYYY-MM-DD HH:MM' (giờ VN)"},
                "message": {"type": "string", "description": "Nội dung mới"},
            },
            "required": ["query"],
        },
    },
}
_DELETE_POLL_SPEC = {
    "type": "function",
    "function": {
        "name": "delete_poll",
        "description": (
            "Xoá cuộc bình chọn (poll) gần nhất mà bot đã tạo trong kênh này. Gọi khi user nói "
            "'xoá poll', 'gỡ bình chọn', 'huỷ vote'."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}
_SUBSCRIBE_SPEC = {
    "type": "function",
    "function": {
        "name": "subscribe",
        "description": (
            "Đăng ký nhận tin ĐỊNH KỲ HẰNG NGÀY về một chủ đề (vd 'tin chứng khoán trong nước', "
            "'giá vàng', 'thời tiết Hà Nội'). Gọi khi user nói 'mỗi ngày cập nhật...', "
            "'hằng ngày báo cho tao...', 'theo dõi giúp...'. Bot sẽ tự tra tin mới + tóm tắt mỗi ngày."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Chủ đề cần cập nhật hằng ngày"},
                "time": {
                    "type": "string",
                    "description": "Giờ đăng mỗi ngày 'HH:MM' giờ VN (mặc định 08:00 nếu không nói)",
                },
            },
            "required": ["topic"],
        },
    },
}
_UNSUBSCRIBE_SPEC = {
    "type": "function",
    "function": {
        "name": "unsubscribe",
        "description": (
            "Ngừng / huỷ đăng ký nhận tin định kỳ. Gọi khi user nói 'đừng cập nhật ... nữa', "
            "'thôi không theo dõi ... nữa', 'huỷ đăng ký ...', 'cắt tin ...', 'bỏ theo dõi ...', "
            "'tắt tin ...', 'ngừng ...'. Khi user nêu RÕ chủ đề muốn ngừng, GỌI THẲNG unsubscribe với "
            "'query'=chủ đề đó (vd 'cắt tin chứng khoán' -> query='chứng khoán'), ĐỪNG gọi "
            "list_subscriptions trước. Nhiều cái khớp thì tool tự trả danh sách để hỏi lại. "
            "'all'=true khi user muốn huỷ HẾT."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Từ khoá chủ đề (tuỳ chọn)"},
                "all": {"type": "boolean", "description": "true = huỷ TẤT CẢ đăng ký của người đó"},
            },
        },
    },
}
_EDIT_SUBSCRIPTION_SPEC = {
    "type": "function",
    "function": {
        "name": "edit_subscription",
        "description": (
            "Sửa đăng ký nhận tin: đổi GIỜ đăng và/hoặc CHỦ ĐỀ. Gọi khi user nói 'đổi giờ cập nhật ... "
            "sang ...', 'sửa đăng ký ...', 'chuyển tin ... sang giờ ...', 'đổi tin ... thành ...'. Khi "
            "user đã nêu RÕ đăng ký nào + giá trị mới, GỌI THẲNG tool này (query=chủ đề cũ, time/topic=giá "
            "trị mới), ĐỪNG gọi list_subscriptions trước. Nhiều cái khớp thì tool tự trả danh sách hỏi "
            "lại. 'time'='HH:MM' (giờ VN), 'topic'=chủ đề mới. Cần ít nhất một trong time/topic."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Từ khoá chủ đề tìm đăng ký cần sửa"},
                "time": {"type": "string", "description": "Giờ mới 'HH:MM' giờ VN"},
                "topic": {"type": "string", "description": "Chủ đề mới"},
            },
            "required": ["query"],
        },
    },
}
_LIST_SUBSCRIPTIONS_SPEC = {
    "type": "function",
    "function": {
        "name": "list_subscriptions",
        "description": (
            "Liệt kê các đăng ký nhận tin định kỳ ĐANG BẬT của người ra lệnh (chủ đề + giờ). "
            "Gọi khi user hỏi 'tao đang theo dõi gì', hoặc khi muốn huỷ mà chưa rõ cái nào."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}


def tool_specs(has_search: bool, include_actions: bool = False) -> list[dict]:
    specs = [
        _REMEMBER_SPEC,
        _REMIND_SPEC,
        _LIST_REMINDERS_SPEC,
        _CANCEL_REMINDER_SPEC,
        _EDIT_REMINDER_SPEC,
        _CREATE_POLL_SPEC,
        _DELETE_POLL_SPEC,
        _SUBSCRIBE_SPEC,
        _UNSUBSCRIBE_SPEC,
        _EDIT_SUBSCRIPTION_SPEC,
        _LIST_SUBSCRIPTIONS_SPEC,
        _SERVER_INFO_SPEC,
        _CURRENT_TIME_SPEC,
    ]
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


def _vn_remind_at(r) -> datetime:
    """remind_at (UTC, có thể naive từ SQLite) -> datetime giờ VN."""
    dt = r.remind_at if r.remind_at.tzinfo is not None else r.remind_at.replace(tzinfo=UTC)
    return dt.astimezone(VN_TZ)


def _fmt_reminder(r) -> str:
    """1 dòng cho người đọc: 'HH:MM dd/mm — nội dung'."""
    return f"{_vn_remind_at(r).strftime('%H:%M %d/%m')} — {r.message}"


def _buoi(h: int) -> str:
    """Buổi trong ngày theo giờ (để khớp 'sáng/chiều/tối...')."""
    if 5 <= h <= 10:
        return "sáng"
    if 11 <= h <= 12:
        return "trưa"
    if 13 <= h <= 17:
        return "chiều"
    if 18 <= h <= 22:
        return "tối"
    return "đêm"


def _reminder_haystack(r) -> str:
    """Gom NỘI DUNG + nhiều biến thể GIỜ (24h, 12h kèm buổi, ngày) để khớp query người dùng —
    cho phép xoá theo '7h tối', '19h', '19:00' hay theo nội dung. Tất cả viết thường."""
    dt = _vn_remind_at(r)
    h, h12 = dt.hour, (dt.hour % 12 or 12)
    buoi = _buoi(h)
    variants = [
        dt.strftime("%H:%M"),  # 19:00
        f"{h}h",  # 19h
        f"{h} giờ",
        f"{h12}h {buoi}",  # 7h tối
        f"{h12} giờ {buoi}",
        f"{h12}h",
        buoi,
        dt.strftime("%d/%m"),
    ]
    return f"{r.message or ''} {' '.join(variants)}".lower()


async def _my_pending(ctx: ToolContext) -> list:
    """Các lời nhắc đang chờ CỦA CHÍNH người ra lệnh."""
    rows = await ctx.reminder_repo.pending_for_guild(ctx.guild_pk)
    return [r for r in rows if r.creator_id == (ctx.commander_id or 0)]


async def _list_reminders(ctx: ToolContext) -> str:
    """Liệt kê nhắc đang chờ của người ra lệnh — để họ thấy & chọn cái cần xoá."""
    if ctx.reminder_repo is None or ctx.guild_pk is None:
        return "Chưa xem được (thiếu ngữ cảnh)."
    mine = await _my_pending(ctx)
    if not mine:
        return "Bạn không có lời nhắc nào đang chờ."
    lines = "\n".join(f"{i + 1}. {_fmt_reminder(r)}" for i, r in enumerate(mine))
    return f"Lời nhắc đang chờ của bạn:\n{lines}"


async def _cancel_reminder(args: dict, ctx: ToolContext) -> str:
    """Huỷ nhắc CỦA CHÍNH người ra lệnh. Nhiều cái khớp -> LIỆT KÊ hỏi lại (không xoá nhầm).
    all=true -> xoá hết. query rỗng + còn nhiều -> cũng liệt kê để chọn."""
    if ctx.reminder_repo is None or ctx.guild_pk is None:
        return "Chưa huỷ được (thiếu ngữ cảnh)."
    mine = await _my_pending(ctx)
    if not mine:
        return "Bạn không có lời nhắc nào đang chờ."
    if bool(args.get("all")):
        for r in mine:
            await ctx.reminder_repo.cancel(r.id, ctx.guild_pk)
        return f"Đã huỷ tất cả {len(mine)} lời nhắc."
    query = str(args.get("query", "")).strip().lower()
    # Khớp query trong NỘI DUNG hoặc GIỜ (19:00 / 19h / 7h tối...). Trống -> lấy hết.
    matched = [r for r in mine if query in _reminder_haystack(r)] if query else mine
    if not matched:
        lines = "\n".join(f"- {_fmt_reminder(r)}" for r in mine)
        return f"Không thấy nhắc nào khớp '{query}'. Bạn đang có:\n{lines}"
    if len(matched) > 1:
        # Mơ hồ -> liệt kê, để model hỏi lại user cho rõ, KHÔNG xoá bừa.
        lines = "\n".join(f"- {_fmt_reminder(r)}" for r in matched)
        return f"Có {len(matched)} nhắc khớp, nói rõ hơn (theo giờ hoặc nội dung) nhé:\n{lines}"
    await ctx.reminder_repo.cancel(matched[0].id, ctx.guild_pk)
    return f"Đã huỷ nhắc: {_fmt_reminder(matched[0])}"


async def _edit_reminder(args: dict, ctx: ToolContext) -> str:
    """Sửa giờ/nội dung 1 lời nhắc của người ra lệnh. Nhiều cái khớp -> liệt kê hỏi lại."""
    if ctx.reminder_repo is None or ctx.guild_pk is None:
        return "Chưa sửa được (thiếu ngữ cảnh)."
    mine = await _my_pending(ctx)
    if not mine:
        return "Bạn không có lời nhắc nào đang chờ."
    query = str(args.get("query", "")).strip().lower()
    matched = [r for r in mine if query in _reminder_haystack(r)] if query else mine
    if not matched:
        lines = "\n".join(f"- {_fmt_reminder(r)}" for r in mine)
        return f"Không thấy nhắc nào khớp '{query}'. Bạn đang có:\n{lines}"
    if len(matched) > 1:
        lines = "\n".join(f"- {_fmt_reminder(r)}" for r in matched)
        return f"Có {len(matched)} nhắc khớp, nói rõ hơn nhé:\n{lines}"
    new_when = str(args.get("when", "")).strip()
    new_msg = str(args.get("message", "")).strip()
    if not new_when and not new_msg:
        return "Cần nêu giờ mới hoặc nội dung mới để sửa."
    remind_at = None
    if new_when:
        remind_at = _parse_vn_to_utc(new_when)
        if remind_at is None:
            return "Giờ mới không hiểu — cho dạng 'YYYY-MM-DD HH:MM' (giờ VN) nhé."
        if remind_at <= datetime.now(UTC):
            return "Giờ mới đã qua rồi, chọn lúc trong tương lai đi."
    updated = await ctx.reminder_repo.update_reminder(
        matched[0].id, ctx.guild_pk, remind_at=remind_at, message=(new_msg or None)
    )
    if updated is None:
        return "Không sửa được lời nhắc đó."
    return f"Đã cập nhật nhắc: {_fmt_reminder(updated)}"


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


def _parse_hhmm(raw: str, default: tuple = (8, 0)) -> tuple:
    """'HH:MM' / '8h' / '8h30' (giờ VN) -> (hour, minute). Không parse được -> default (08:00)."""
    raw = (raw or "").strip().lower().replace("giờ", "h")
    for fmt in ("%H:%M", "%Hh%M", "%Hh", "%H"):
        try:
            t = datetime.strptime(raw, fmt)
            return t.hour, t.minute
        except ValueError:
            continue
    return default


async def _subscribe(args: dict, ctx: ToolContext) -> str:
    """Tạo đăng ký nhận tin hằng ngày. Nếu giờ hẹn đã qua trong hôm nay -> bắt đầu từ NGÀY MAI."""
    if ctx.subscription_repo is None or ctx.guild_pk is None or ctx.channel_id is None:
        return "Chưa đăng ký được (thiếu ngữ cảnh)."
    topic = str(args.get("topic", "")).strip()
    if not topic:
        return "Cần nêu chủ đề muốn cập nhật (vd 'tin chứng khoán trong nước')."
    hour, minute = _parse_hhmm(str(args.get("time", "")))
    now_vn = datetime.now(VN_TZ)
    # Giờ hẹn đã trôi qua hôm nay -> đánh dấu đã chạy hôm nay để lần đầu là NGÀY MAI (đỡ bắn ngay).
    last_run_on = now_vn.date() if (hour, minute) <= (now_vn.hour, now_vn.minute) else None
    await ctx.subscription_repo.create(
        guild_id=ctx.guild_pk,
        channel_id=ctx.channel_id,
        creator_id=ctx.commander_id or 0,
        topic=topic,
        hour=hour,
        minute=minute,
        last_run_on=last_run_on,
    )
    return f"Đã đăng ký: mỗi ngày {hour:02d}:{minute:02d} cập nhật '{topic}'."


async def _my_subs(ctx: ToolContext) -> list:
    return await ctx.subscription_repo.active_for_creator(ctx.guild_pk, ctx.commander_id or 0)


async def _list_subscriptions(ctx: ToolContext) -> str:
    if ctx.subscription_repo is None or ctx.guild_pk is None:
        return "Chưa xem được (thiếu ngữ cảnh)."
    mine = await _my_subs(ctx)
    if not mine:
        return "Bạn chưa đăng ký nhận tin định kỳ nào."
    lines = "\n".join(
        f"{i + 1}. {s.hour:02d}:{s.minute:02d} — {s.topic}" for i, s in enumerate(mine)
    )
    return f"Đăng ký nhận tin của bạn:\n{lines}"


async def _unsubscribe(args: dict, ctx: ToolContext) -> str:
    """Huỷ đăng ký CỦA CHÍNH người ra lệnh. Nhiều cái khớp -> liệt kê hỏi lại; all=true -> huỷ hết."""
    if ctx.subscription_repo is None or ctx.guild_pk is None:
        return "Chưa huỷ được (thiếu ngữ cảnh)."
    mine = await _my_subs(ctx)
    if not mine:
        return "Bạn không có đăng ký nào đang bật."
    if bool(args.get("all")):
        for s in mine:
            await ctx.subscription_repo.cancel(s.id, ctx.guild_pk)
        return f"Đã huỷ tất cả {len(mine)} đăng ký."
    query = str(args.get("query", "")).strip().lower()
    matched = [s for s in mine if query in (s.topic or "").lower()] if query else mine
    if not matched:
        lines = "\n".join(f"- {s.topic} ({s.hour:02d}:{s.minute:02d})" for s in mine)
        return f"Không thấy đăng ký nào khớp '{query}'. Bạn đang có:\n{lines}"
    if len(matched) > 1:
        lines = "\n".join(f"- {s.topic} ({s.hour:02d}:{s.minute:02d})" for s in matched)
        return f"Có {len(matched)} đăng ký khớp, nói rõ chủ đề nào nhé:\n{lines}"
    await ctx.subscription_repo.cancel(matched[0].id, ctx.guild_pk)
    return f"Đã huỷ đăng ký: {matched[0].topic}"


async def _edit_subscription(args: dict, ctx: ToolContext) -> str:
    """Sửa giờ/chủ đề 1 đăng ký của người ra lệnh. Nhiều cái khớp -> liệt kê hỏi lại.
    Đổi giờ -> reset last_run_on để lịch mới có hiệu lực (đỡ chờ tới mai)."""
    if ctx.subscription_repo is None or ctx.guild_pk is None:
        return "Chưa sửa được (thiếu ngữ cảnh)."
    mine = await _my_subs(ctx)
    if not mine:
        return "Bạn không có đăng ký nào đang bật."
    query = str(args.get("query", "")).strip().lower()
    matched = [s for s in mine if query in (s.topic or "").lower()] if query else mine
    if not matched:
        lines = "\n".join(f"- {s.topic} ({s.hour:02d}:{s.minute:02d})" for s in mine)
        return f"Không thấy đăng ký nào khớp '{query}'. Bạn đang có:\n{lines}"
    if len(matched) > 1:
        lines = "\n".join(f"- {s.topic} ({s.hour:02d}:{s.minute:02d})" for s in matched)
        return f"Có {len(matched)} đăng ký khớp, nói rõ chủ đề nào nhé:\n{lines}"
    new_time = str(args.get("time", "")).strip()
    new_topic = str(args.get("topic", "")).strip()
    if not new_time and not new_topic:
        return "Cần nêu giờ mới hoặc chủ đề mới để sửa."
    kwargs: dict = {"topic": new_topic or None}
    if new_time:
        hour, minute = _parse_hhmm(new_time)
        kwargs["hour"], kwargs["minute"] = hour, minute
        now_vn = datetime.now(VN_TZ)
        # Đổi giờ -> reset last_run_on: giờ mới còn tới hôm nay thì chạy hôm nay, đã qua thì mai.
        kwargs["last_run_on"] = (
            None if (hour, minute) > (now_vn.hour, now_vn.minute) else now_vn.date()
        )
    updated = await ctx.subscription_repo.update(matched[0].id, ctx.guild_pk, **kwargs)
    if updated is None:
        return "Không sửa được đăng ký đó."
    return (
        f"Đã cập nhật: mỗi ngày {updated.hour:02d}:{updated.minute:02d} cập nhật '{updated.topic}'."
    )


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
    if name == "list_reminders":
        return await _list_reminders(ctx)
    if name == "cancel_reminder":
        return await _cancel_reminder(args, ctx)
    if name == "edit_reminder":
        return await _edit_reminder(args, ctx)
    if name == "create_poll":
        return _stage_poll(args, ctx)
    if name == "delete_poll":
        from app.services.ai.actions.registry import PendingAction  # lazy: tránh vòng import

        ctx.pending.append(PendingAction("delete_poll", False, "Xoá poll gần nhất", {}))
        return "Đã xoá poll gần nhất."
    if name == "subscribe":
        return await _subscribe(args, ctx)
    if name == "unsubscribe":
        return await _unsubscribe(args, ctx)
    if name == "edit_subscription":
        return await _edit_subscription(args, ctx)
    if name == "list_subscriptions":
        return await _list_subscriptions(ctx)
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
        # Hành động PHÁ -> chờ nút ✅/❌. Hành động an toàn -> hệ thống làm NGAY (không cần confirm).
        # Báo đúng để model khỏi nói nhầm "chờ admin confirm" cho việc tự chạy ngay.
        if res.destructive:
            return f"Đã xếp hàng: {res.description}. Hệ thống sẽ hiện nút ✅/❌ cho admin xác nhận."
        return f"Đã thực hiện: {res.description}."
    log.info("agent tool called: name=%s", name)
    return f"Tool không tồn tại: {name}"
