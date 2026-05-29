import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.http_exceptions import ConflictError
from app.models.custom_command import CustomCommand


class CustomCommandRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, *, guild_id: uuid.UUID, command_id: uuid.UUID) -> CustomCommand | None:
        r = await self.session.execute(
            select(CustomCommand).where(
                CustomCommand.id == command_id, CustomCommand.guild_id == guild_id
            )
        )
        return r.scalar_one_or_none()

    async def get_by_trigger(self, *, guild_id: uuid.UUID, trigger: str) -> CustomCommand | None:
        r = await self.session.execute(
            select(CustomCommand).where(
                CustomCommand.guild_id == guild_id,
                func.lower(CustomCommand.trigger) == trigger.lower(),
            )
        )
        return r.scalar_one_or_none()

    async def list_by_guild(
        self, guild_id: uuid.UUID, enabled_only: bool = False
    ) -> list[CustomCommand]:
        conditions = [CustomCommand.guild_id == guild_id]
        if enabled_only:
            conditions.append(CustomCommand.enabled.is_(True))
        r = await self.session.execute(
            select(CustomCommand).where(*conditions).order_by(CustomCommand.trigger)
        )
        return list(r.scalars().all())

    async def create(self, *, guild_id: uuid.UUID, data: dict[str, Any]) -> CustomCommand:
        trigger = str(data["trigger"]).lower()
        if await self.get_by_trigger(guild_id=guild_id, trigger=trigger) is not None:
            raise ConflictError(
                detail=f"A command with trigger '{trigger}' already exists",
                error_code="DUPLICATE_TRIGGER",
            )
        cmd = CustomCommand(
            guild_id=guild_id,
            trigger=trigger,
            response_type=data.get("response_type", "text"),
            response_text=data.get("response_text"),
            embed=data.get("embed"),
            allowed_role_ids=data.get("allowed_role_ids", []),
            allowed_channel_ids=data.get("allowed_channel_ids", []),
            cooldown_seconds=data.get("cooldown_seconds", 0),
            enabled=data.get("enabled", True),
            created_by=data.get("created_by"),
        )
        self.session.add(cmd)
        await self.session.flush()
        await self.session.refresh(cmd)
        return cmd

    async def update(
        self, *, guild_id: uuid.UUID, command_id: uuid.UUID, data: dict[str, Any]
    ) -> CustomCommand | None:
        cmd = await self.get(guild_id=guild_id, command_id=command_id)
        if cmd is None:
            return None
        if "trigger" in data:
            new_trigger = str(data["trigger"]).lower()
            existing = await self.get_by_trigger(guild_id=guild_id, trigger=new_trigger)
            if existing is not None and existing.id != command_id:
                raise ConflictError(
                    detail=f"A command with trigger '{new_trigger}' already exists",
                    error_code="DUPLICATE_TRIGGER",
                )
            cmd.trigger = new_trigger
        for field in (
            "response_type",
            "response_text",
            "embed",
            "allowed_role_ids",
            "allowed_channel_ids",
            "cooldown_seconds",
            "enabled",
        ):
            if field in data:
                setattr(cmd, field, data[field])
        await self.session.flush()
        await self.session.refresh(cmd)
        return cmd

    async def delete(self, *, guild_id: uuid.UUID, command_id: uuid.UUID) -> bool:
        cmd = await self.get(guild_id=guild_id, command_id=command_id)
        if cmd is None:
            return False
        await self.session.delete(cmd)
        await self.session.flush()
        return True
