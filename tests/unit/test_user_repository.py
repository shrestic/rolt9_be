import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.user import UserRepository


@pytest_asyncio.fixture
async def repo(db_session: AsyncSession) -> UserRepository:
    return UserRepository(db_session)


async def _make_user(repo: UserRepository, discord_id: int = 111) -> User:
    return await repo.upsert(
        discord_id=discord_id,
        username="alice",
        avatar_url=None,
        access_token_enc=b"a",
        refresh_token_enc=b"b",
        token_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


@pytest.mark.asyncio
async def test_upsert_creates_new_user(repo: UserRepository):
    u = await _make_user(repo)
    assert isinstance(u.id, uuid.UUID)
    assert u.discord_id == 111


@pytest.mark.asyncio
async def test_upsert_updates_existing_user(repo: UserRepository):
    u1 = await _make_user(repo, 111)
    u2 = await repo.upsert(
        discord_id=111,
        username="alice2",
        avatar_url="x",
        access_token_enc=b"c",
        refresh_token_enc=b"d",
        token_expires_at=datetime.now(UTC) + timedelta(hours=2),
    )
    assert u1.id == u2.id
    assert u2.username == "alice2"


@pytest.mark.asyncio
async def test_get_by_id_returns_user(repo: UserRepository):
    u = await _make_user(repo)
    found = await repo.get_by_id(u.id)
    assert found is not None
    assert found.discord_id == 111


@pytest.mark.asyncio
async def test_get_by_id_missing_returns_none(repo: UserRepository):
    assert await repo.get_by_id(uuid.uuid4()) is None
