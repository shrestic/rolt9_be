import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        result = await self.session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_discord_id(self, discord_id: int) -> User | None:
        result = await self.session.execute(select(User).where(User.discord_id == discord_id))
        return result.scalar_one_or_none()

    async def upsert(
        self,
        *,
        discord_id: int,
        username: str,
        avatar_url: str | None,
        access_token_enc: bytes,
        refresh_token_enc: bytes,
        token_expires_at: datetime,
    ) -> User:
        existing = await self.get_by_discord_id(discord_id)
        if existing is None:
            user = User(
                discord_id=discord_id,
                username=username,
                avatar_url=avatar_url,
                access_token_enc=access_token_enc,
                refresh_token_enc=refresh_token_enc,
                token_expires_at=token_expires_at,
            )
            self.session.add(user)
            await self.session.commit()
            await self.session.refresh(user)
            return user
        existing.username = username
        existing.avatar_url = avatar_url
        existing.access_token_enc = access_token_enc
        existing.refresh_token_enc = refresh_token_enc
        existing.token_expires_at = token_expires_at
        await self.session.commit()
        await self.session.refresh(existing)
        return existing
