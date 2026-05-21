import uuid
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt

from app.core.config import settings


def create_session_token(user_id: uuid.UUID) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.JWT_TTL_MINUTES)).timestamp()),
        "iss": settings.JWT_ISSUER,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_session_token(token: str) -> uuid.UUID | None:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return uuid.UUID(payload["sub"])
    except (JWTError, KeyError, ValueError):
        return None
