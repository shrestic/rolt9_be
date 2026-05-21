from fastapi import Cookie, Depends

from app.core.security import decode_session_token
from app.dependencies.services import get_user_repository
from app.exceptions.http_exceptions import UnauthorizedError
from app.models.user import User
from app.repositories.user import UserRepository

SESSION_COOKIE = "rolt9_session"


async def get_current_user(
    rolt9_session: str | None = Cookie(default=None),
    user_repo: UserRepository = Depends(get_user_repository),
) -> User:
    if not rolt9_session:
        raise UnauthorizedError(error_code="NO_SESSION", detail="No session cookie")
    user_id = decode_session_token(rolt9_session)
    if user_id is None:
        raise UnauthorizedError(error_code="INVALID_SESSION", detail="Invalid session")
    user = await user_repo.get_by_id(user_id)
    if user is None:
        raise UnauthorizedError(error_code="USER_NOT_FOUND", detail="User not found")
    return user
