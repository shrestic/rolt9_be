import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.guild import GuildRepository
from app.repositories.guild_settings import GuildSettingsRepository

log = logging.getLogger(__name__)


async def handle_guild_join(guild, db: AsyncSession) -> None:
    guilds = GuildRepository(db)
    settings_repo = GuildSettingsRepository(db)
    icon_url = getattr(getattr(guild, "icon", None), "url", None)
    g = await guilds.upsert(discord_id=int(guild.id), name=guild.name, icon_url=icon_url)
    await settings_repo.create_defaults(g.id)
    log.info("guild_join: %s (%s)", guild.name, guild.id)


async def handle_guild_remove(guild, db: AsyncSession) -> None:
    await GuildRepository(db).mark_inactive(int(guild.id))
    log.info("guild_remove: %s (%s)", guild.name, guild.id)
