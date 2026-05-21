from fastapi import APIRouter

from app.api.v1.endpoints import auth, guilds, health, me

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(me.router, prefix="/me", tags=["me"])
api_router.include_router(guilds.router, prefix="/guilds", tags=["guilds"])
