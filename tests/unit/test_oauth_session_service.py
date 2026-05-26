from datetime import UTC, datetime, timedelta

import pytest

from app.core.crypto import decrypt_str, encrypt_str
from app.discord_io.errors import DiscordError
from app.discord_io.types import OAuthTokens
from app.models.user import User
from app.repositories.user import UserRepository
from app.services.oauth_session import OAuthSessionService, SessionExpiredError
from tests.fakes.discord import FakeOAuthClient


@pytest.mark.asyncio
async def test_returns_existing_token_when_not_near_expiry(db_session):
    u = User(
        discord_id=1,
        username="a",
        avatar_url=None,
        access_token_enc=encrypt_str("STILL-GOOD"),
        refresh_token_enc=encrypt_str("RT"),
        token_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)

    oauth = FakeOAuthClient()
    svc = OAuthSessionService(oauth=oauth)
    token = await svc.get_valid_access_token(u, UserRepository(db_session))
    assert token == "STILL-GOOD"
    assert oauth.refresh_calls == 0


@pytest.mark.asyncio
async def test_refreshes_when_near_expiry(db_session):
    u = User(
        discord_id=1,
        username="a",
        avatar_url=None,
        access_token_enc=encrypt_str("OLD"),
        refresh_token_enc=encrypt_str("RT-OLD"),
        token_expires_at=datetime.now(UTC) + timedelta(seconds=30),
    )
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)

    oauth = FakeOAuthClient()
    oauth.refreshed["RT-OLD"] = OAuthTokens(
        access_token="NEW",
        refresh_token="RT-NEW",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        scope="identify guilds",
    )

    svc = OAuthSessionService(oauth=oauth)
    token = await svc.get_valid_access_token(u, UserRepository(db_session))
    assert token == "NEW"
    assert oauth.refresh_calls == 1

    refreshed = await UserRepository(db_session).get_by_id(u.id)
    assert decrypt_str(refreshed.access_token_enc) == "NEW"
    assert decrypt_str(refreshed.refresh_token_enc) == "RT-NEW"


@pytest.mark.asyncio
async def test_refresh_failure_raises_session_expired(db_session):
    # If Discord rejects the refresh token (revoked / corrupted / etc.) the
    # only recovery is for the user to log in again. The service surfaces
    # SessionExpiredError so the API can translate it to HTTP 401.
    u = User(
        discord_id=1,
        username="a",
        avatar_url=None,
        access_token_enc=encrypt_str("OLD"),
        refresh_token_enc=encrypt_str("REVOKED"),
        token_expires_at=datetime.now(UTC) + timedelta(seconds=30),
    )
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)

    class FailingOAuthClient(FakeOAuthClient):
        async def refresh_oauth_token(self, refresh_token: str):
            self.refresh_calls += 1
            raise DiscordError("invalid_grant")

    oauth = FailingOAuthClient()
    svc = OAuthSessionService(oauth=oauth)
    with pytest.raises(SessionExpiredError):
        await svc.get_valid_access_token(u, UserRepository(db_session))
    assert oauth.refresh_calls == 1
