"""Server Companion AI — dựng snapshot hoạt động server + AI tự quyết SKIP/buông câu.

`build_snapshot` thuần (test được, không I/O). `CompanionService.decide` gọi AIGateway;
lỗi cấu hình AI (off/thiếu key/hết budget) -> trả None (proactive: im lặng, không spam lỗi).
"""

import logging

import discord

from app.services.ai.ai_gateway import AIGateway

log = logging.getLogger(__name__)

_DEFAULT_PERSONA = "Bạn là một thành viên AI của server Discord, tính cách lầy lội nhưng dễ thương."


def build_companion_system(persona: str, memory_doc: str = "") -> str:
    base = persona or _DEFAULT_PERSONA
    parts = [base]
    if memory_doc.strip():
        # Lore server (biệt danh/luật/tính cách) — để companion buông câu đúng "chất" server.
        parts.append(f"\nTRÍ NHỚ SERVER (luôn áp dụng):\n{memory_doc.strip()}")
    parts.append(
        "\nDưới đây là TÌNH HÌNH SERVER lúc này. "
        "MẶC ĐỊNH hãy trả về đúng chữ SKIP — đa số trường hợp KHÔNG có gì đáng nói. "
        "CHỈ buông MỘT câu ngắn, duyên, tự nhiên (tiếng Việt) khi THẬT SỰ có khoảnh khắc đáng "
        "(ai đang chơi/nghe/xem gì đó một mình, ai vừa làm gì hay ho để cà khịa hoặc rủ rê). "
        "Đừng nói chỉ để nói, đừng lặp lại điều vừa nói, đừng chào hỏi máy móc — thà im còn hơn nhảm.\n"
        "Mỗi người có kèm '<@id>': bạn CÓ THỂ @tag họ bằng cách copy NGUYÊN cụm '<@id>' đó vào câu "
        "(vd 'Ê <@111> chơi một mình à, <@222> vào gánh đi'). Chỉ tag khi hợp lý, đừng tag loạn.\n"
        "TUYỆT ĐỐI KHÔNG tag hay nhắc tới CHÍNH MÌNH (con bot) — chỉ nói về người khác."
    )
    return "\n".join(parts)


def _tag(m) -> str:
    """'Tên (<@id>)' — cho model VỪA gọi tên thân mật VỪA @ping thật được (copy cụm <@id>)."""
    name = getattr(m, "display_name", None) or str(m)
    mention = getattr(m, "mention", None)  # discord.Member.mention -> '<@id>'
    return f"{name} ({mention})" if mention else name


# Các loại activity "đáng để ý" + động từ tiếng Việt. KHÔNG gồm custom status (đổi liên tục,
# nhiễu). 'playing' xử riêng để gộp "chơi 1 mình / N người" (phần rủ-vào-gánh).
_ACTIVITY_VERB = {
    discord.ActivityType.streaming: "stream",
    discord.ActivityType.listening: "nghe",
    discord.ActivityType.watching: "xem",
    discord.ActivityType.competing: "thi đấu",
}


def _interesting_activities(member) -> list[tuple]:
    """[(ActivityType, tên)] các hoạt động đáng để ý của member (gồm cả playing)."""
    out = []
    for act in getattr(member, "activities", []) or []:
        t = getattr(act, "type", None)
        name = getattr(act, "name", None)
        if name and (t == discord.ActivityType.playing or t in _ACTIVITY_VERB):
            out.append((t, name))
    return out


def build_snapshot(members, voice_channels, recent_messages, bot_id) -> str | None:
    """Mô tả hoạt động hiện tại (chơi game / nghe / xem / stream + voice + chat). Mỗi người
    kèm '<@id>' để model @ping đúng người. Trả None nếu không có gì."""
    games: dict[str, list[str]] = {}
    other_lines = []  # nghe/xem/stream/thi đấu — không gộp, mỗi người 1 dòng
    for m in members or []:
        if getattr(m, "bot", False) or getattr(m, "id", None) == bot_id:
            continue
        for t, name in _interesting_activities(m):
            if t == discord.ActivityType.playing:
                games.setdefault(name, []).append(_tag(m))
            else:
                other_lines.append(f"- {_tag(m)} đang {_ACTIVITY_VERB[t]} {name}")

    game_lines = []
    for game, players in games.items():
        if len(players) == 1:
            game_lines.append(f"- {players[0]} đang chơi {game} MỘT MÌNH")
        else:
            game_lines.append(f"- {len(players)} người đang chơi {game}: {', '.join(players)}")

    voice_lines = []
    for ch in voice_channels or []:
        mem = [_tag(x) for x in getattr(ch, "members", []) if not getattr(x, "bot", False)]
        if not mem:
            continue
        if len(mem) == 1:
            voice_lines.append(f"- {mem[0]} đang ngồi voice [{ch.name}] một mình")
        else:
            voice_lines.append(f"- Voice [{ch.name}]: {', '.join(mem)}")

    chat_lines = []
    for msg in recent_messages or []:
        author = getattr(msg, "author", None)
        if author is None or getattr(author, "bot", False):
            continue
        content = (getattr(msg, "content", "") or "").strip()
        if content:
            chat_lines.append(f"- {_tag(author)}: {content[:80]}")

    parts = []
    if game_lines:
        parts.append("ĐANG CHƠI GAME:\n" + "\n".join(game_lines))
    if other_lines:
        parts.append("HOẠT ĐỘNG KHÁC (nghe/xem/stream):\n" + "\n".join(other_lines))
    if voice_lines:
        parts.append("VOICE:\n" + "\n".join(voice_lines))
    if chat_lines:
        parts.append("CHAT GẦN ĐÂY:\n" + "\n".join(chat_lines))
    if not parts:
        return None
    return "\n\n".join(parts)


def _activity_label(t, name) -> str:
    """(type, tên) -> nhãn tiếng Việt, vd 'chơi Valorant' / 'nghe Spotify'."""
    verb = "chơi" if t == discord.ActivityType.playing else _ACTIVITY_VERB.get(t, "làm")
    return f"{verb} {name}"


def newly_started_activities(before, after) -> list[str]:
    """Nhãn các hoạt động VỪA bắt đầu: có ở 'after' mà chưa có ở 'before'. Bắt đúng khoảnh
    khắc 'vừa mở game/Spotify/stream...' (bỏ qua các presence update khác). VD ['chơi Valorant'].
    Dùng tên activity (vd 'Spotify') nên đổi bài hát KHÔNG tính là mới -> đỡ spam."""
    before_set = set(_interesting_activities(before))
    new = [pair for pair in _interesting_activities(after) if pair not in before_set]
    return sorted(_activity_label(t, name) for t, name in new)


def current_activity_labels(member) -> list[str]:
    """Nhãn MỌI hoạt động ĐANG diễn ra của member (vd ['chơi Valorant']). Dùng để dedupe
    'game này đã báo trong phiên chơi hiện tại chưa' + quên khi game đã tắt."""
    return sorted(_activity_label(t, name) for t, name in _interesting_activities(member))


def build_event_snapshot(member, activities, members, voice_channels, bot_id) -> str:
    """Snapshot cho sự kiện 'vừa bắt đầu hoạt động': nêu rõ ai vừa làm gì (kèm <@id> để @ping),
    rồi gắn bối cảnh hiện tại (ai đang chơi/nghe/ngồi voice) để model tự quyết có nên rủ rê/cà khịa."""
    head = f"VỪA MỚI: {_tag(member)} vừa {', '.join(activities)}."
    body = build_snapshot(members, voice_channels, [], bot_id)
    return f"{head}\n\n{body}" if body else head


class CompanionService:
    def __init__(self, *, gateway: AIGateway):
        self.gateway = gateway

    async def decide(
        self, *, guild_discord_id: int, snapshot: str, persona: str, memory_doc: str = ""
    ) -> str | None:
        try:
            out = await self.gateway.complete(
                guild_discord_id=guild_discord_id,
                system=build_companion_system(persona, memory_doc),
                prompt=snapshot,
            )
        except ValueError:
            return None  # AI off / thiếu key / hết budget -> im lặng
        out = (out or "").strip()
        if not out or out.upper().startswith("SKIP"):
            return None
        return out
