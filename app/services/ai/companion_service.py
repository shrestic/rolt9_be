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
        "\nDưới đây là TÌNH HÌNH SERVER lúc này. Nếu có gì đáng để buông MỘT câu ngắn, "
        "duyên, tự nhiên (tiếng Việt) — cà khịa nhẹ hoặc bắt chuyện — thì trả về đúng câu đó. "
        "Nếu KHÔNG có gì đáng nói, trả về đúng chữ SKIP. Đừng spam, đừng lặp lại, "
        "không chào hỏi máy móc."
    )
    return "\n".join(parts)


def build_snapshot(members, voice_channels, recent_messages, bot_id) -> str | None:
    """Mô tả hoạt động hiện tại (game/voice/chat). Trả None nếu không có gì."""
    games: dict[str, list[str]] = {}
    for m in members or []:
        if getattr(m, "bot", False) or getattr(m, "id", None) == bot_id:
            continue
        for act in getattr(m, "activities", []) or []:
            if getattr(act, "type", None) == discord.ActivityType.playing and getattr(
                act, "name", None
            ):
                games.setdefault(act.name, []).append(getattr(m, "display_name", str(m)))

    game_lines = []
    for game, players in games.items():
        if len(players) == 1:
            game_lines.append(f"- {players[0]} đang chơi {game} MỘT MÌNH")
        else:
            game_lines.append(f"- {len(players)} người đang chơi {game}: {', '.join(players)}")

    voice_lines = []
    for ch in voice_channels or []:
        mem = [
            getattr(x, "display_name", str(x))
            for x in getattr(ch, "members", [])
            if not getattr(x, "bot", False)
        ]
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
            chat_lines.append(f"- {getattr(author, 'display_name', '?')}: {content[:80]}")

    parts = []
    if game_lines:
        parts.append("ĐANG CHƠI GAME:\n" + "\n".join(game_lines))
    if voice_lines:
        parts.append("VOICE:\n" + "\n".join(voice_lines))
    if chat_lines:
        parts.append("CHAT GẦN ĐÂY:\n" + "\n".join(chat_lines))
    if not parts:
        return None
    return "\n\n".join(parts)


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
