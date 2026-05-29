from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    badges,
    commands,
    currency,
    guilds,
    health,
    leveling,
    me,
    moderation,
)

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(me.router, prefix="/me", tags=["me"])
api_router.include_router(guilds.router, prefix="/guilds", tags=["guilds"])
api_router.include_router(moderation.router, prefix="/guilds", tags=["moderation"])
api_router.include_router(commands.router, prefix="/guilds", tags=["commands"])
api_router.include_router(leveling.router, prefix="/guilds", tags=["leveling"])
api_router.include_router(currency.router, prefix="/guilds", tags=["currency"])
api_router.include_router(badges.router, prefix="/guilds", tags=["badges"])
