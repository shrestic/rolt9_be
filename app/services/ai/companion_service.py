"""Server Companion AI — builds a snapshot of server activity + lets the AI decide to SKIP or drop a line.

`build_snapshot` is pure (testable, no I/O). `CompanionService.decide` calls AIGateway;
on an AI config error (off/missing key/out of budget) -> returns None (proactive: stays quiet, doesn't spam errors).
"""

import logging

import discord

from app.services.ai.ai_gateway import AIGateway

log = logging.getLogger(__name__)

_DEFAULT_PERSONA = "You're an AI member of this Discord server, mischievous but lovable."


def build_companion_system(persona: str, memory_doc: str = "") -> str:
    base = persona or _DEFAULT_PERSONA
    parts = [base]
    if memory_doc.strip():
        # Server lore (nicknames/rules/personality) — so the companion drops lines that match the server's vibe.
        parts.append(f"\nSERVER MEMORY (always apply):\n{memory_doc.strip()}")
    parts.append(
        "\nHere's the SERVER SITUATION right now. "
        "By DEFAULT just return the exact word SKIP — most of the time there's NOTHING worth saying. "
        "ONLY drop ONE short, witty, natural line (in English) when there's GENUINELY a moment for it "
        "(someone playing/listening/watching something alone, someone just did something cool worth roasting or hyping up). "
        "Don't talk just to talk, don't repeat what was just said, don't do robotic greetings — better to stay quiet than be lame.\n"
        "Each person comes with a '<@id>': you CAN @tag them by copying that exact '<@id>' into your line "
        "(e.g. 'Yo <@111> playing solo huh, <@222> get in there and carry'). Only tag when it makes sense, don't tag randomly.\n"
        "ABSOLUTELY DO NOT tag or mention YOURSELF (the bot) — only talk about other people."
    )
    return "\n".join(parts)


def _tag(m) -> str:
    """'Name (<@id>)' — lets the model BOTH call them by a friendly name AND actually @ping them (copy the <@id>)."""
    name = getattr(m, "display_name", None) or str(m)
    mention = getattr(m, "mention", None)  # discord.Member.mention -> '<@id>'
    return f"{name} ({mention})" if mention else name


# The "noteworthy" activity types + their English verbs. Does NOT include custom status (changes
# constantly, noisy). 'playing' is handled separately to group "playing solo / N people" (the carry-invite bit).
_ACTIVITY_VERB = {
    discord.ActivityType.streaming: "streaming",
    discord.ActivityType.listening: "listening to",
    discord.ActivityType.watching: "watching",
    discord.ActivityType.competing: "competing in",
}


def _interesting_activities(member) -> list[tuple]:
    """[(ActivityType, name)] the member's noteworthy activities (including playing)."""
    out = []
    for act in getattr(member, "activities", []) or []:
        t = getattr(act, "type", None)
        name = getattr(act, "name", None)
        if name and (t == discord.ActivityType.playing or t in _ACTIVITY_VERB):
            out.append((t, name))
    return out


def build_snapshot(members, voice_channels, recent_messages, bot_id) -> str | None:
    """Describe current activity (playing games / listening / watching / streaming + voice + chat). Each person
    comes with a '<@id>' so the model can @ping the right person. Returns None if there's nothing."""
    games: dict[str, list[str]] = {}
    other_lines = []  # listening/watching/streaming/competing — not grouped, one line per person
    for m in members or []:
        if getattr(m, "bot", False) or getattr(m, "id", None) == bot_id:
            continue
        for t, name in _interesting_activities(m):
            if t == discord.ActivityType.playing:
                games.setdefault(name, []).append(_tag(m))
            else:
                other_lines.append(f"- {_tag(m)} is {_ACTIVITY_VERB[t]} {name}")

    game_lines = []
    for game, players in games.items():
        if len(players) == 1:
            game_lines.append(f"- {players[0]} is playing {game} ALONE")
        else:
            game_lines.append(f"- {len(players)} people playing {game}: {', '.join(players)}")

    voice_lines = []
    for ch in voice_channels or []:
        mem = [_tag(x) for x in getattr(ch, "members", []) if not getattr(x, "bot", False)]
        if not mem:
            continue
        if len(mem) == 1:
            voice_lines.append(f"- {mem[0]} is sitting in voice [{ch.name}] alone")
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
        parts.append("PLAYING GAMES:\n" + "\n".join(game_lines))
    if other_lines:
        parts.append("OTHER ACTIVITY (listening/watching/streaming):\n" + "\n".join(other_lines))
    if voice_lines:
        parts.append("VOICE:\n" + "\n".join(voice_lines))
    if chat_lines:
        parts.append("RECENT CHAT:\n" + "\n".join(chat_lines))
    if not parts:
        return None
    return "\n\n".join(parts)


def _activity_label(t, name) -> str:
    """(type, name) -> an English label, e.g. 'playing Valorant' / 'listening to Spotify'."""
    verb = "playing" if t == discord.ActivityType.playing else _ACTIVITY_VERB.get(t, "doing")
    return f"{verb} {name}"


def newly_started_activities(before, after) -> list[str]:
    """Labels for activities that JUST started: present in 'after' but not in 'before'. Catches the exact
    moment 'just opened a game/Spotify/stream...' (ignores other presence updates). E.g. ['playing Valorant'].
    Uses the activity name (e.g. 'Spotify') so switching songs does NOT count as new -> less spam."""
    before_set = set(_interesting_activities(before))
    new = [pair for pair in _interesting_activities(after) if pair not in before_set]
    return sorted(_activity_label(t, name) for t, name in new)


def current_activity_labels(member) -> list[str]:
    """Labels for ALL of the member's CURRENTLY-running activities (e.g. ['playing Valorant']). Used to dedupe
    'have we already announced this game in the current play session' + forget it once the game is off."""
    return sorted(_activity_label(t, name) for t, name in _interesting_activities(member))


def build_event_snapshot(member, activities, members, voice_channels, bot_id) -> str:
    """Snapshot for a 'just started an activity' event: spells out who just did what (with <@id> for @pinging),
    then attaches the current context (who's playing/listening/sitting in voice) so the model can decide whether to hype/roast."""
    head = f"JUST NOW: {_tag(member)} just started {', '.join(activities)}."
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
            return None  # AI off / missing key / out of budget -> stay quiet
        out = (out or "").strip()
        if not out or out.upper().startswith("SKIP"):
            return None
        return out
