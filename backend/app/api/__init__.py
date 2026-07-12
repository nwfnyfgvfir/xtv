from fastapi import APIRouter

from app.api import health, libraries, media, playback, scan, settings

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router, tags=["health"])
api_router.include_router(libraries.router, prefix="/libraries", tags=["libraries"])
api_router.include_router(media.router, prefix="/media", tags=["media"])
api_router.include_router(playback.router, tags=["playback"])
api_router.include_router(scan.router, tags=["scan"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
