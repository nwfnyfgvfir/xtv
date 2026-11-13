from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings
from app.schemas import HealthOut
from app.services.metatube import MetaTubeClient
from app.services.stash import StashClient
from app.services.watcher import watcher_status

router = APIRouter()


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    settings = get_settings()
    metatube: dict | None = None
    stash: dict | None = None
    source = "stash" if settings.scrape_source == "stash" else "metatube"
    try:
        client = StashClient(settings) if source == "stash" else MetaTubeClient(settings)
        data = await client.ping()
        result = {"ok": True, "data": data}
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "error": str(exc)}
    if source == "stash":
        stash = result
    else:
        metatube = result
    watcher: dict | None = None
    try:
        watcher = watcher_status()
    except Exception:  # noqa: BLE001
        watcher = {"running": False}
    return HealthOut(
        status="ok",
        version=settings.version,
        metatube=metatube,
        stash=stash,
        scrape_source=source,
        auth_enabled=settings.auth_enabled,
        watcher=watcher,
    )
