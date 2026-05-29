# Handlers for the bot's lifecycle events on Discord:
#   - on_guild_join   → bot was just added to a new guild → upsert + create defaults
#   - on_guild_remove → bot was kicked / guild deleted    → mark inactive (DB row kept)
#   - on_guild_update → guild metadata changed (name/icon) → upsert to keep DB in sync
#   - on_ready        → bot finished connecting           → backfill guilds it was already in
#
# Handlers take GuildInfo (our dataclass), not discord.Guild — the conversion
# happens at the event boundary in bot/client.py. As a result this module
# has no discord.py dependency.

import logging
from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.discord_io.types import GuildInfo
from app.repositories.guild import GuildRepository
from app.repositories.guild_settings import GuildSettingsRepository

log = logging.getLogger(__name__)


async def handle_guild_join(guild: GuildInfo, db: AsyncSession) -> None:
    guilds = GuildRepository(db)
    settings_repo = GuildSettingsRepository(db)

    # upsert: re-joining after a kick flips is_active back to True and updates
    # the name/icon.
    g = await guilds.upsert(discord_id=guild.discord_id, name=guild.name, icon_url=guild.icon_url)
    # Create empty settings for a brand-new guild (idempotent — keeps existing
    # settings if there are any).
    await settings_repo.create_defaults(g.id)
    log.info("guild_join: %s (%s)", guild.name, guild.discord_id)


async def handle_guild_remove(guild: GuildInfo, db: AsyncSession) -> None:
    # Soft-delete: just mark inactive. mod_case history is preserved.
    await GuildRepository(db).mark_inactive(guild.discord_id)
    log.info("guild_remove: %s (%s)", guild.name, guild.discord_id)


# Fires when guild metadata changes on Discord (name, icon, owner, etc.).
# We only persist name + icon, so an idempotent upsert keeps the DB in sync
# without disturbing guild_settings or any other related rows.
async def handle_guild_update(guild: GuildInfo, db: AsyncSession) -> None:
    await GuildRepository(db).upsert(
        discord_id=guild.discord_id, name=guild.name, icon_url=guild.icon_url
    )
    log.info("guild_update: %s (%s)", guild.name, guild.discord_id)


# on_guild_join only fires when the bot ENTERS a new guild. Guilds the bot
# was already in at process start do NOT trigger a join event — so without
# this backfill the `guilds` table would be empty for them, and /me/guilds
# would report bot_present=false.
async def handle_ready(guilds: Iterable[GuildInfo], db: AsyncSession) -> None:
    count = 0
    for guild in guilds:
        # Reuse handle_guild_join — upsert is idempotent, so re-calling is safe.
        await handle_guild_join(guild, db)
        count += 1
    log.info("ready: backfilled %d guild(s)", count)
