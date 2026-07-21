from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings
from app.schemas import HealthOut
from app.services.metatube import MetaTubeClient, MetaTubeError
from app.services.watcher import watcher_status

router = APIRouter()


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    settings = get_settings()
    metatube: dict | None = None
    try:
        data = await MetaTubeClient().ping()
        metatube = {"ok": True, "data": data}
    except MetaTubeError as exc:
        metatube = {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        metatube = {"ok": False, "error": str(exc)}
    watcher: dict | None = None
    try:
        watcher = watcher_status()
    except Exception:  # noqa: BLE001
        watcher = {"running": False}
    return HealthOut(
        status="ok",
        metatube=metatube,
        auth_enabled=settings.auth_enabled,
        watcher=watcher,
    )
