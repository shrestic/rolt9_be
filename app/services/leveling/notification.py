"""Level-up notifications.

When a member's level goes up, the bot tells someone about it. *Who* gets
told is per-guild configurable:

    NotificationMode.CHANNEL  → post in `notification_channel_id`
    NotificationMode.DM       → DM the member directly
    NotificationMode.OFF      → don't notify at all (silent leveling)

This module owns that decision and the corresponding Discord call. It is
intentionally a thin layer over `DiscordClient` — no Pillow, no DB, no
business rules beyond "what channel / who".

Important contract: **every Discord-side failure is logged and swallowed.**
The level-up itself was already persisted upstream (in `XpAwarder.award`),
so a delivery hiccup here (permission denied on the notification channel,
member has DMs closed, etc.) must never roll back the XP write. The next
level-up will retry by virtue of being a fresh event.
"""

import logging

from app.core.enums import NotificationMode
from app.discord_io.client import DiscordClient
from app.discord_io.errors import DiscordError
from app.models.guild_leveling_config import GuildLevelingConfig

log = logging.getLogger(__name__)


class LevelUpNotifier:
    """Posts a single level-up message according to the guild's `notification_mode`.

    Holds only a `DiscordClient` — no state, no caches. Safe to instantiate
    per request or share across the process.
    """

    def __init__(self, discord_io: DiscordClient):
        """Store the Discord client dependency.

        Args:
            discord_io: The bot's `BotDiscordClient`, sourced from
                `app.state.bot` in HTTP requests or from the cog in
                slash-command paths. Tests pass a `FakeDiscordClient`.
        """
        self.discord_io = discord_io

    async def send(
        self,
        *,
        config: GuildLevelingConfig,
        user_id: int,
        username: str,
        new_level: int,
    ) -> None:
        """Send (or skip) a level-up notification.

        The flow is:

            1. Read `config.notification_mode`.
            2. If OFF → return immediately.
            3. Build the message text once.
            4. Dispatch to the right Discord call based on the mode.
            5. On `DiscordError`: log a warning and swallow — never raise.

        Why we swallow: this function runs inside the same DB transaction
        as the XP write (see `LevelingService.process_message`). If we let
        a Discord 403 propagate, the transaction would roll back and the
        member would lose the XP they just earned. Silently dropping the
        notification is much better UX.

        Args:
            config: The full leveling config row. We read `notification_mode`
                and `notification_channel_id` from it; nothing else.
            user_id: Discord snowflake of the leveled-up member. Used as the
                DM target when mode == DM. Not included in the message text
                (we use `username` for display).
            username: Display name to show in the announcement, e.g. the
                guild nickname or username.
            new_level: The level they just reached (the *new* one, not the
                old one). Shown in the message and used to build the DM
                reason string.

        Returns:
            None. The function does not surface success/failure to the
            caller — by design, level-up should not fail the surrounding
            process.

        Example:
            >>> await notifier.send(config=cfg, user_id=42, username="Alice",
            ...                     new_level=5)
            # → posts "🎉 Alice just leveled up to **5**!" to the channel,
            #   DMs Alice, or does nothing, depending on cfg.notification_mode.
        """
        mode = config.notification_mode

        # Mode 1/3: OFF — guild has explicitly silenced level-ups. Bail out
        # before doing any Discord work so we don't log spurious warnings.
        if mode == NotificationMode.OFF:
            return

        # Build the announcement once. Same text for channel and DM paths
        # so they stay visually consistent.
        text = f"🎉 {username} just leveled up to **{new_level}**!"

        try:
            # Mode 2/3: CHANNEL — post in the configured notification channel.
            # The channel field can be NULL (admin set mode without picking a
            # channel yet); in that case we silently no-op rather than guess.
            if mode == NotificationMode.CHANNEL:
                channel_id = config.notification_channel_id
                if channel_id is None:
                    return
                await self.discord_io.post_to_channel(int(channel_id), content=text)

            # Mode 3/3: DM — direct message the member. We reuse the
            # existing `notify_user_of_action` helper because it already
            # handles the "user blocked the bot" edge case gracefully.
            # `guild_name` is set to a generic string because the DM path
            # doesn't have the guild row handy here; the helper just embeds
            # it in the message header.
            elif mode == NotificationMode.DM:
                await self.discord_io.notify_user_of_action(
                    user_id,
                    action=f"level up to {new_level}",
                    guild_name="the server",
                    reason=None,
                )
        except DiscordError as exc:
            # Swallow on purpose — see module docstring. We log a warning
            # so operators can spot persistent delivery problems (bad
            # channel id, missing SEND_MESSAGES permission) in the bot logs.
            log.warning("Failed to send level-up notification: %s", exc)
