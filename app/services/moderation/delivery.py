# "Deliver" a case after the action has succeeded and the DB row is written:
#   1. Post the embed to the mod-log channel (if the guild has one configured)
#   2. DM the target user about the action (if dm_on_action is enabled)
#
# Both steps are best-effort: any error (channel deleted, user blocked DMs,
# bot lost permission) is logged but NEVER raised. The primary action
# (ban/kick/mute) has already completed — we won't roll back a ban just
# because a DM failed.

import logging

from app.discord_io.client import DiscordMessaging
from app.discord_io.errors import DiscordError
from app.models.mod_case import ModCase
from app.services.moderation.embeds import build_case_embed

log = logging.getLogger(__name__)


async def deliver_case(
    discord_io: DiscordMessaging,
    *,
    guild_name: str,
    mod_settings: dict,
    target_user_id: int,
    case: ModCase,
) -> None:
    # Build the embed once, reused for the mod-log post.
    embed = build_case_embed(case)

    # Step 1: post to mod-log channel if the admin configured one.
    channel_id = (mod_settings or {}).get("mod_log_channel_id")
    if channel_id:
        try:
            await discord_io.post_to_channel(int(channel_id), embed=embed)
        except DiscordError:
            log.warning(
                "Failed to post case #%s to mod-log channel %s", case.case_number, channel_id
            )

    # Step 2: DM the target if the admin enabled dm_on_action.
    if (mod_settings or {}).get("dm_on_action"):
        try:
            await discord_io.notify_user_of_action(
                target_user_id,
                action=case.action,
                guild_name=guild_name,
                reason=case.reason,
            )
        except DiscordError:
            log.info("Could not DM user %s", target_user_id)
