# Build an Embed (our dataclass) from a ModCase. Does NOT import discord —
# the adapter converts Embed → discord.Embed (BotDiscordClient) or JSON dict
# (RestDiscordClient) when actually posting.

from app.discord_io.types import Embed, EmbedField
from app.models.mod_case import ModCase

# Per-action color so case embeds are visually distinguishable in mod-log.
_COLORS = {
    "ban": 0xED4245,  # red
    "kick": 0xE67E22,  # orange
    "mute": 0xFAA61A,  # yellow-orange
    "unmute": 0x57F287,  # green (revert)
    "unban": 0x57F287,  # green (revert)
    "warn": 0xFEE75C,  # light yellow
}


def build_case_embed(case: ModCase) -> Embed:
    # Two mandatory fields: target user and the acting moderator.
    fields = [
        EmbedField(
            name="User",
            value=f"{case.target_username} (`{case.target_user_id}`)",
        ),
        EmbedField(name="Moderator", value=case.moderator_username, inline=True),
    ]

    # Auto-escalation cases (mute/ban triggered by /warn) — show source so the
    # moderator can tell it wasn't a manual action.
    if case.source == "escalation":
        fields.append(EmbedField(name="Source", value="Auto-escalation", inline=True))

    # Mutes have duration; ban/kick/warn do not.
    if case.duration_seconds:
        fields.append(EmbedField(name="Duration", value=f"{case.duration_seconds}s", inline=True))

    # Reason always goes last, not inline (often long).
    fields.append(EmbedField(name="Reason", value=case.reason or "No reason given"))

    return Embed(
        title=f"Case #{case.case_number} · {case.action.upper()}",
        color=_COLORS.get(case.action, 0x5865F2),
        fields=fields,
    )
