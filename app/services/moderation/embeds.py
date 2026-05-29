# Build an Embed (our dataclass) from a ModCase. Does NOT import discord —
# the adapter converts Embed → discord.Embed (BotDiscordClient) or JSON dict
# (RestDiscordClient) when actually posting.

from app.core.colors import ModerationColors
from app.discord_io.types import Embed, EmbedField
from app.models.mod_case import ModCase


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
        color=ModerationColors.for_action(case.action),
        fields=fields,
    )
