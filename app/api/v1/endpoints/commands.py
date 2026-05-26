import uuid

from fastapi import APIRouter, Depends, Response, status

from app.dependencies.auth import get_current_user
from app.dependencies.guild import require_managed_guild
from app.dependencies.services import (
    get_custom_command_repository,
    get_discord_io,
    get_guild_settings_repository,
)
from app.discord_io.client import DiscordClient
from app.exceptions.http_exceptions import NotFoundError
from app.models.custom_command import CustomCommand
from app.models.guild import Guild
from app.models.user import User
from app.repositories.custom_command import CustomCommandRepository
from app.repositories.guild_settings import GuildSettingsRepository
from app.schemas.custom_command import (
    CommandPreviewRequest,
    CommandPreviewResponse,
    CommandSettings,
    CustomCommandIn,
    CustomCommandOut,
    EmbedSpec,
    PlaceholderInfo,
    RenderedEmbed,
)
from app.services.custom_command_service import (
    PLACEHOLDERS,
    build_context,
    render_embed_spec,
    render_template,
)

router = APIRouter()


def _to_out(c: CustomCommand) -> CustomCommandOut:
    return CustomCommandOut(
        id=str(c.id),
        trigger=c.trigger,
        response_type=c.response_type,
        response_text=c.response_text,
        embed=EmbedSpec(**c.embed) if c.embed else None,
        allowed_role_ids=[str(x) for x in (c.allowed_role_ids or [])],
        allowed_channel_ids=[str(x) for x in (c.allowed_channel_ids or [])],
        cooldown_seconds=c.cooldown_seconds,
        enabled=c.enabled,
    )


def _to_data(payload: CustomCommandIn) -> dict:
    return {
        "trigger": payload.trigger,
        "response_type": payload.response_type,
        "response_text": payload.response_text,
        "embed": payload.embed.model_dump() if payload.embed else None,
        "allowed_role_ids": [int(x) for x in payload.allowed_role_ids],
        "allowed_channel_ids": [int(x) for x in payload.allowed_channel_ids],
        "cooldown_seconds": payload.cooldown_seconds,
        "enabled": payload.enabled,
    }


@router.get("/{guild_id}/commands", response_model=list[CustomCommandOut])
async def list_commands(
    guild: Guild = Depends(require_managed_guild),
    repo: CustomCommandRepository = Depends(get_custom_command_repository),
):
    return [_to_out(c) for c in await repo.list_by_guild(guild.id)]


@router.post(
    "/{guild_id}/commands",
    response_model=CustomCommandOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_command(
    payload: CustomCommandIn,
    guild: Guild = Depends(require_managed_guild),
    repo: CustomCommandRepository = Depends(get_custom_command_repository),
):
    cmd = await repo.create(guild_id=guild.id, data=_to_data(payload))
    return _to_out(cmd)


@router.get("/{guild_id}/commands/{command_id}", response_model=CustomCommandOut)
async def get_command(
    command_id: uuid.UUID,
    guild: Guild = Depends(require_managed_guild),
    repo: CustomCommandRepository = Depends(get_custom_command_repository),
):
    cmd = await repo.get(guild_id=guild.id, command_id=command_id)
    if cmd is None:
        raise NotFoundError(detail="Command not found")
    return _to_out(cmd)


@router.put("/{guild_id}/commands/{command_id}", response_model=CustomCommandOut)
async def update_command(
    command_id: uuid.UUID,
    payload: CustomCommandIn,
    guild: Guild = Depends(require_managed_guild),
    repo: CustomCommandRepository = Depends(get_custom_command_repository),
):
    cmd = await repo.update(guild_id=guild.id, command_id=command_id, data=_to_data(payload))
    if cmd is None:
        raise NotFoundError(detail="Command not found")
    return _to_out(cmd)


@router.delete("/{guild_id}/commands/{command_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_command(
    command_id: uuid.UUID,
    guild: Guild = Depends(require_managed_guild),
    repo: CustomCommandRepository = Depends(get_custom_command_repository),
):
    if not await repo.delete(guild_id=guild.id, command_id=command_id):
        raise NotFoundError(detail="Command not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{guild_id}/command-settings", response_model=CommandSettings)
async def get_command_settings(
    guild: Guild = Depends(require_managed_guild),
    settings_repo: GuildSettingsRepository = Depends(get_guild_settings_repository),
):
    gs = await settings_repo.get(guild.id)
    return CommandSettings(**((gs.commands if gs else {}) or {}))


@router.put("/{guild_id}/command-settings", response_model=CommandSettings)
async def update_command_settings(
    payload: CommandSettings,
    guild: Guild = Depends(require_managed_guild),
    settings_repo: GuildSettingsRepository = Depends(get_guild_settings_repository),
):
    gs = await settings_repo.update_section(guild.id, "commands", payload.model_dump())
    return CommandSettings(**gs.commands)


# Live preview for the dashboard. Substitutes the placeholders in the
# moderator's draft using:
#   - the calling user as {user} / {user.mention}
#   - the real guild as {server} / {member_count} (cache read via bot)
# Lets the admin see exactly what the command will output before saving.
@router.post("/{guild_id}/commands/preview", response_model=CommandPreviewResponse)
async def preview_command(
    payload: CommandPreviewRequest,
    guild: Guild = Depends(require_managed_guild),
    current: User = Depends(get_current_user),
    discord_io: DiscordClient = Depends(get_discord_io),
):
    # Pull live guild info from the bot's gateway cache — same source the cog
    # uses at runtime, so the preview matches what the bot will actually post.
    guild_info = await discord_io.get_guild(guild.discord_id)

    context = build_context(
        user_display=current.username,
        user_mention=f"<@{current.discord_id}>",
        server_name=guild_info.name,
        member_count=guild_info.member_count,
    )

    rendered_text: str | None = None
    rendered_embed: RenderedEmbed | None = None

    if payload.response_type == "text" and payload.response_text:
        rendered_text = render_template(payload.response_text, context)
    elif payload.response_type == "embed" and payload.embed:
        embed = render_embed_spec(payload.embed.model_dump(), context)
        rendered_embed = RenderedEmbed(
            title=embed.title,
            description=embed.description,
            color=embed.color,
            footer=embed.footer,
            image_url=embed.image_url,
        )

    # Echo the placeholder registry with the concrete values used in this
    # render — gives the FE everything it needs to render a help section.
    placeholders = [
        PlaceholderInfo(name=p.name, description=p.description, example=context[p.name])
        for p in PLACEHOLDERS
    ]
    return CommandPreviewResponse(
        rendered_text=rendered_text,
        rendered_embed=rendered_embed,
        placeholders=placeholders,
    )
