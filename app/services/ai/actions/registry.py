"""Claw Agent Actions — stage (validate) + execute (thực thi) hành động server.

Action tool trong tool-loop chỉ STAGE (validate + tạo PendingAction). Cog mới execute:
hành động an toàn làm ngay, hành động PHÁ (ban/kick/timeout/delete_role) chờ nút ✅.
Gate per-action theo quyền Discord của người ra lệnh; bot phải đủ quyền + cấp bậc.
"""

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from app.repositories.ai_config import AIConfigRepository
from app.repositories.currency_config import CurrencyConfigRepository
from app.repositories.guild import GuildRepository
from app.repositories.karma_config import KarmaConfigRepository
from app.repositories.leveling_config import GuildLevelingConfigRepository
from app.repositories.minigame_config import MinigameConfigRepository
from app.repositories.welcome_config import WelcomeConfigRepository

log = logging.getLogger(__name__)


@dataclass
class PendingAction:
    kind: str
    destructive: bool
    description: str
    params: dict = field(default_factory=dict)


# action kind -> tên flag perm Discord người ra lệnh cần có
ACTION_PERMS = {
    "create_role": "manage_roles",
    "assign_role": "manage_roles",
    "remove_role": "manage_roles",
    "delete_role": "manage_roles",
    "toggle_plugin": "manage_guild",
    "kick": "kick_members",
    "ban": "ban_members",
    "unban": "ban_members",
    "timeout": "moderate_members",
    "untimeout": "moderate_members",
}
# Hành động PHÁ cần nút ✅ xác nhận. unban/untimeout là hành động KHÔI PHỤC
# (gỡ phạt) nên KHÔNG phá → chạy ngay, không cần xác nhận.
DESTRUCTIVE = {"delete_role", "kick", "ban", "timeout"}

# plugin name -> (RepoClass, field). Mọi repo đều có upsert(guild_id, data).
PLUGIN_TOGGLES = {
    "leveling": (GuildLevelingConfigRepository, "enabled"),
    "currency": (CurrencyConfigRepository, "enabled"),
    "welcome": (WelcomeConfigRepository, "enabled"),
    "minigame": (MinigameConfigRepository, "enabled"),
    "karma": (KarmaConfigRepository, "enabled"),
    "ai": (AIConfigRepository, "enabled"),
    "agent": (AIConfigRepository, "agent_enabled"),
    "tools": (AIConfigRepository, "tools_enabled"),
}

_PERM_LABEL = {
    "manage_roles": "Manage Roles",
    "manage_guild": "Manage Guild",
    "kick_members": "Kick Members",
    "ban_members": "Ban Members",
    "moderate_members": "Moderate Members",
}

ACTION_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "create_role",
            "description": "Tạo một role mới trong server.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "color": {"type": "string", "description": "Mã hex #rrggbb (tùy chọn)"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assign_role",
            "description": "Gán một role cho (các) user được nhắc tới, hoặc cho chính người ra lệnh nếu không nhắc ai.",
            "parameters": {
                "type": "object",
                "properties": {"role_name": {"type": "string"}},
                "required": ["role_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_role",
            "description": "Gỡ một role khỏi (các) user được nhắc, hoặc chính người ra lệnh.",
            "parameters": {
                "type": "object",
                "properties": {"role_name": {"type": "string"}},
                "required": ["role_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_role",
            "description": "Xóa một role khỏi server (hành động phá, cần xác nhận).",
            "parameters": {
                "type": "object",
                "properties": {"role_name": {"type": "string"}},
                "required": ["role_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "toggle_plugin",
            "description": "Bật hoặc tắt một plugin của bot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "plugin": {"type": "string", "enum": list(PLUGIN_TOGGLES)},
                    "enabled": {"type": "boolean"},
                },
                "required": ["plugin", "enabled"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kick",
            "description": "Kick (các) user được nhắc khỏi server (hành động phá, cần xác nhận).",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ban",
            "description": "Ban (các) user được nhắc khỏi server (hành động phá, cần xác nhận).",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "timeout",
            "description": "Timeout / mute tạm (cấm chat) các user được nhắc (hành động phá, cần xác nhận).",
            "parameters": {
                "type": "object",
                "properties": {
                    "minutes": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["minutes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "untimeout",
            "description": (
                "Gỡ timeout / unmute cho (các) user được nhắc — cho họ chat lại ngay. Gọi NGAY khi "
                "user nói 'gỡ mute', 'unmute', 'bỏ timeout', 'mở mồm cho X', 'cho X nói lại', "
                "'tha cho X'. ĐỪNG chỉ trả lời bằng lời — phải gọi tool."
            ),
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "unban",
            "description": (
                "Gỡ ban (unban) cho một user. Vì người bị ban đã RỜI server (không @ được), "
                "hãy truyền 'user' là TÊN hoặc ID của họ; nếu vẫn @ được thì bot dùng người được nhắc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user": {"type": "string", "description": "Tên hoặc ID người cần gỡ ban"},
                    "reason": {"type": "string"},
                },
            },
        },
    },
]


def _parse_color(raw):
    """Hex '#rrggbb' -> int, hoặc None nếu không parse được."""
    if not raw:
        return None
    s = str(raw).strip().lstrip("#")
    try:
        return int(s, 16)
    except ValueError:
        return None


def _find_role_name(role_name: str, role_names: list[str]) -> str | None:
    low = role_name.strip().lower()
    for r in role_names:
        if r.lower() == low:
            return r
    return None


async def stage(name: str, args: dict, ctx) -> "PendingAction | str":
    """Validate + gate quyền. Trả PendingAction (chờ cog execute) hoặc chuỗi lỗi cho model."""
    perm = ACTION_PERMS.get(name)
    if perm is None:
        return f"Hành động không hỗ trợ: {name}"
    if not ctx.commander_perms.get(perm):
        return f"Bạn cần quyền {_PERM_LABEL.get(perm, perm)} để làm việc này."

    destructive = name in DESTRUCTIVE

    if name == "create_role":
        rn = str(args.get("name", "")).strip()
        if not rn or len(rn) > 100:
            return "Tên role không hợp lệ (1-100 ký tự)."
        color = _parse_color(args.get("color"))
        return PendingAction(name, destructive, f"Tạo role **{rn}**", {"name": rn, "color": color})

    if name in ("assign_role", "remove_role", "delete_role"):
        rn = str(args.get("role_name", "")).strip()
        if not rn:
            return "Thiếu tên role."
        match = _find_role_name(rn, ctx.role_names)
        # assign_role CHO PHÉP role chưa tồn tại: có thể được create_role tạo CÙNG LƯỢT
        # (cog chạy create trước assign). Kiểm tra tồn tại thật để ở execute. remove/delete
        # cần role có sẵn -> vẫn từ chối sớm cho rõ.
        if match is None and name != "assign_role":
            return f"Không tìm thấy role '{rn}' trong server."
        role_label = match or rn
        if name == "delete_role":
            return PendingAction(
                name, destructive, f"Xóa role **{role_label}**", {"role_name": role_label}
            )
        targets = list(ctx.target_user_ids) or ([ctx.commander_id] if ctx.commander_id else [])
        if not targets:
            return "Không rõ gán/gỡ cho ai."
        verb = "Gán" if name == "assign_role" else "Gỡ"
        return PendingAction(
            name,
            destructive,
            f"{verb} role **{role_label}** cho {len(targets)} người",
            {"role_name": role_label, "target_ids": targets},
        )

    if name == "toggle_plugin":
        plugin = str(args.get("plugin", "")).strip().lower()
        if plugin not in PLUGIN_TOGGLES:
            return f"Plugin không hợp lệ. Hợp lệ: {', '.join(PLUGIN_TOGGLES)}"
        enabled = bool(args.get("enabled"))
        return PendingAction(
            name,
            destructive,
            f"{'Bật' if enabled else 'Tắt'} plugin **{plugin}**",
            {"plugin": plugin, "enabled": enabled},
        )

    if name in ("kick", "ban", "timeout"):
        targets = list(ctx.target_user_ids)
        if not targets:
            return f"Cần @ người cần {name}."
        params = {"target_ids": targets, "reason": str(args.get("reason", "") or "")}
        if name == "timeout":
            minutes = args.get("minutes")
            if not isinstance(minutes, int) or minutes <= 0:
                return "Số phút timeout phải > 0."
            params["minutes"] = minutes
            desc = f"Timeout {len(targets)} người {minutes} phút"
        else:
            desc = f"{name.capitalize()} {len(targets)} người"
        return PendingAction(name, destructive, desc, params)

    if name == "untimeout":
        # Gỡ mute: cần người còn trong server (mention được).
        targets = list(ctx.target_user_ids)
        if not targets:
            return "Cần @ người cần gỡ timeout/unmute."
        return PendingAction(
            name,
            False,
            f"Gỡ timeout {len(targets)} người",
            {"target_ids": targets, "reason": str(args.get("reason", "") or "")},
        )

    if name == "unban":
        # Người bị ban đã rời server → ưu tiên tra theo tên/ID ('user'); mention (nếu có) cũng nhận.
        targets = list(ctx.target_user_ids)
        query = str(args.get("user", "") or "").strip()
        if not targets and not query:
            return "Cần nhập TÊN hoặc ID người cần gỡ ban (họ đã rời server nên không @ được)."
        return PendingAction(
            name,
            False,
            f"Gỡ ban: {query or f'{len(targets)} người'}",
            {"target_ids": targets, "query": query, "reason": str(args.get("reason", "") or "")},
        )

    return f"Hành động không hỗ trợ: {name}"


async def execute(pending: PendingAction, *, guild, session, channel=None) -> str:
    """Thực thi thật. guild = discord.Guild; session = AsyncSession; channel = kênh để gửi
    (poll cần). Lỗi -> chuỗi báo."""
    import datetime

    import discord

    p = pending.params
    try:
        if pending.kind == "create_poll":
            if channel is None:
                return "Không gửi được poll (thiếu kênh)."
            poll = discord.Poll(
                question=p["question"],
                duration=datetime.timedelta(hours=p["duration_hours"]),
                multiple=p["multiple"],
            )
            for opt in p["options"]:
                poll.add_answer(text=opt[:55])  # Discord giới hạn 55 ký tự/đáp án
            await channel.send(poll=poll)
            return f"Đã tạo poll: {p['question']}"

        if pending.kind == "delete_poll":
            if channel is None:
                return "Không xoá được poll (thiếu kênh)."
            me_id = guild.me.id if guild is not None and guild.me is not None else None
            # Quét vài tin gần đây, tìm poll DO BOT tạo để xoá (xoá tin = xoá poll).
            async for m in channel.history(limit=30):
                if getattr(m, "poll", None) is not None and (
                    me_id is None or getattr(m.author, "id", None) == me_id
                ):
                    await m.delete()
                    return "Đã xoá poll gần nhất."
            return "Không thấy poll nào gần đây để xoá."

        if pending.kind == "create_role":
            kwargs = {"name": p["name"]}
            if p.get("color") is not None:
                kwargs["colour"] = discord.Colour(p["color"])
            await guild.create_role(**kwargs)
            return f"Đã tạo role {p['name']}."

        if pending.kind in ("assign_role", "remove_role", "delete_role"):
            role = discord.utils.find(
                lambda r: r.name.lower() == p["role_name"].lower(), guild.roles
            )
            if role is None:
                return f"Role {p['role_name']} không còn nữa."
            if guild.me.top_role <= role:
                return f"Role {role.name} đứng trên/ngang role của bot — không thao tác được."
            if pending.kind == "delete_role":
                await role.delete()
                return f"Đã xóa role {role.name}."
            done = 0
            for uid in p["target_ids"]:
                member = guild.get_member(uid)
                if member is None:
                    continue
                if pending.kind == "assign_role":
                    await member.add_roles(role)
                else:
                    await member.remove_roles(role)
                done += 1
            verb = "gán" if pending.kind == "assign_role" else "gỡ"
            return f"Đã {verb} role {role.name} cho {done} người."

        if pending.kind in ("kick", "ban", "timeout"):
            done = 0
            blocked: list[str] = []  # người có role ≥ bot — bỏ qua, KHÔNG chặn cả lô
            for uid in p["target_ids"]:
                member = guild.get_member(uid)
                # Cấp bậc: chỉ chặn khi member còn trong server và role ≥ bot.
                if member is not None and guild.me.top_role <= member.top_role:
                    blocked.append(member.display_name)
                    continue
                if pending.kind == "ban":
                    # Ban được CẢ người đã rời server (ban theo ID qua discord.Object).
                    await guild.ban(
                        member or discord.Object(id=uid), reason=p.get("reason") or None
                    )
                elif member is None:
                    continue  # kick/timeout cần người còn trong server
                elif pending.kind == "kick":
                    await member.kick(reason=p.get("reason") or None)
                else:
                    await member.timeout(
                        timedelta(minutes=p["minutes"]), reason=p.get("reason") or None
                    )
                done += 1
            msg = f"Đã {pending.kind} {done} người."
            if blocked:
                msg += f" Bỏ qua (role cao hơn/ngang bot): {', '.join(blocked)}."
            return msg

        if pending.kind == "untimeout":
            done = 0
            for uid in p["target_ids"]:
                member = guild.get_member(uid)
                if member is None:
                    continue
                await member.timeout(None, reason=p.get("reason") or None)  # None = gỡ timeout
                done += 1
            return f"Đã gỡ timeout {done} người."

        if pending.kind == "unban":
            wanted_ids = set(p.get("target_ids") or [])
            query = (p.get("query") or "").strip().lower().lstrip("@")
            qnorm = query.replace("-", "").replace("_", "").replace(" ", "")
            bans = [e async for e in guild.bans(limit=1000)]

            def _hit(u) -> bool:
                if u.id in wanted_ids:
                    return True
                if not query:
                    return False
                if query == str(u.id):
                    return True
                # Gộp username + global_name + str(user), so khớp lỏng (bỏ -/_/space)
                names = " ".join(
                    x for x in (u.name, getattr(u, "global_name", None), str(u)) if x
                ).lower()
                if query in names:
                    return True
                names_norm = names.replace("-", "").replace("_", "").replace(" ", "")
                return bool(qnorm) and qnorm in names_norm

            matched = [e.user for e in bans if _hit(e.user)]
            if matched:
                for u in matched:
                    await guild.unban(u, reason=p.get("reason") or None)
                return "Đã gỡ ban: " + ", ".join(u.name or str(u.id) for u in matched)
            if not bans:
                return "Danh sách ban đang trống — không có ai để gỡ."
            # Không khớp -> LIỆT KÊ ban list kèm ID (tài khoản đã xoá tên khó gõ, gỡ theo ID).
            lines = "\n".join(f"- {e.user.name or '(no name)'} — ID {e.user.id}" for e in bans[:20])
            return (
                f"Không thấy ai khớp '{query}'. Trong danh sách ban đang có:\n{lines}\n"
                "Gõ lại đúng tên hoặc ID (vd 'gỡ ban 123456') nhé."
            )

        if pending.kind == "toggle_plugin":
            repo_cls, fieldname = PLUGIN_TOGGLES[p["plugin"]]
            g = await GuildRepository(session).get_by_discord_id(guild.id)
            if g is None:
                return "Server chưa đăng ký với bot."
            await repo_cls(session).upsert(g.id, {fieldname: p["enabled"]})
            return f"Đã {'bật' if p['enabled'] else 'tắt'} plugin {p['plugin']}."
    except discord.Forbidden:
        return "Bot không đủ quyền để làm việc này (kiểm tra quyền + cấp bậc role của bot)."
    except discord.HTTPException:
        log.warning("action execute HTTPException kind=%s", pending.kind)
        return "Discord từ chối thao tác, thử lại sau."

    return f"Hành động không hỗ trợ: {pending.kind}"
