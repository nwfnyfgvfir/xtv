from __future__ import annotations

from fastapi import APIRouter

from app.schemas import HealthOut
from app.services.metatube import MetaTubeClient, MetaTubeError

router = APIRouter()


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    mt: dict | None = None
    try:
        client = MetaTubeClient()
        data = await client.ping()
        mt = {"ok": True, "data": data}
    except MetaTubeError as exc:
        mt = {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        mt = {"ok": False, "error": str(exc)}
    return HealthOut(status="ok", metatube=mt)
