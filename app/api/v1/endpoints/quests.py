"""HTTP endpoints for quest CRUD.

Mounted under `/api/v1/guilds/{guild_id}/quests`, gated by
`require_managed_guild`. Quests are per-guild admin-authored definitions; member
progress is not exposed here (that's the `/quests` bot command). Unit-of-Work:
the repo flushes, the request boundary commits.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Path

from app.dependencies.guild import require_managed_guild
from app.dependencies.services import get_quest_repository
from app.models.guild import Guild
from app.models.guild_quest import GuildQuest
from app.repositories.quest import QuestRepository
from app.schemas.quests import QuestIn, QuestOut

router = APIRouter()


def _out(q: GuildQuest) -> QuestOut:
    """Convert a GuildQuest ORM instance to the API response schema."""
    return QuestOut(
        id=str(q.id),
        name=q.name,
        description=q.description,
        period=q.period,
        objective_type=q.objective_type,
        target=q.target,
        reward_coins=q.reward_coins,
        enabled=q.enabled,
    )


@router.get("/{guild_id}/quests", response_model=list[QuestOut])
async def list_quests(
    guild: Guild = Depends(require_managed_guild),
    repo: QuestRepository = Depends(get_quest_repository),
):
    """Return all quests for the guild (enabled and disabled), newest first."""
    return [_out(q) for q in await repo.list_for_guild(guild.id)]


@router.post("/{guild_id}/quests", response_model=QuestOut)
async def create_quest(
    payload: QuestIn,
    guild: Guild = Depends(require_managed_guild),
    repo: QuestRepository = Depends(get_quest_repository),
):
    """Create a new quest definition for the guild."""
    return _out(await repo.create(guild.id, payload.model_dump()))


@router.patch("/{guild_id}/quests/{quest_id}", response_model=QuestOut)
async def update_quest(
    payload: QuestIn,
    quest_id: uuid.UUID = Path(...),
    guild: Guild = Depends(require_managed_guild),
    repo: QuestRepository = Depends(get_quest_repository),
):
    """Update an existing quest definition. Returns 404 if not found in this guild."""
    quest = await repo.get(guild.id, quest_id)
    if quest is None:
        raise HTTPException(status_code=404, detail="Quest not found")
    return _out(await repo.update(quest, payload.model_dump()))


@router.delete("/{guild_id}/quests/{quest_id}")
async def delete_quest(
    quest_id: uuid.UUID = Path(...),
    guild: Guild = Depends(require_managed_guild),
    repo: QuestRepository = Depends(get_quest_repository),
):
    """Delete a quest definition. Returns 404 if not found in this guild."""
    quest = await repo.get(guild.id, quest_id)
    if quest is None:
        raise HTTPException(status_code=404, detail="Quest not found")
    await repo.delete(quest)
    return {"ok": True}
