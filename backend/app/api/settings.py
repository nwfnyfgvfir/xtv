from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import require_auth
from app.models import AppSetting
from app.schemas import SettingsOut, SettingsUpdate
from app.services.metatube import MetaTubeClient

router = APIRouter()

OVERRIDE_KEYS = {
    "metatube_base_url",
    "metatube_token",
    "metatube_provider",
    "metatube_fallback",
    "alist_base_url",
    "alist_token",
    "auto_scrape",
    "scan_extensions",
}


def _db_map(db: Session) -> dict[str, str]:
    rows = db.query(AppSetting).all()
    return {r.key: r.value for r in rows}


def _apply_overrides_to_runtime(db_map: dict[str, str]) -> None:
    s = get_settings()
    if "metatube_base_url" in db_map and db_map["metatube_base_url"]:
        s.metatube_base_url = db_map["metatube_base_url"]
    if "metatube_token" in db_map:
        s.metatube_token = db_map["metatube_token"]
    if "metatube_provider" in db_map:
        s.metatube_provider = db_map["metatube_provider"]
    if "metatube_fallback" in db_map:
        s.metatube_fallback = db_map["metatube_fallback"].lower() in ("1", "true", "yes", "on")
    if "alist_base_url" in db_map and db_map["alist_base_url"]:
        s.alist_base_url = db_map["alist_base_url"]
    if "alist_token" in db_map:
        s.alist_token = db_map["alist_token"]
    if "auto_scrape" in db_map:
        s.auto_scrape = db_map["auto_scrape"].lower() in ("1", "true", "yes", "on")
    if "scan_extensions" in db_map and db_map["scan_extensions"]:
        s.scan_extensions = db_map["scan_extensions"]


async def _providers() -> list[str]:
    try:
        data = await MetaTubeClient().list_providers()
        movies = data.get("movie_providers") or {}
        if isinstance(movies, dict):
            return sorted(movies.keys())
        if isinstance(movies, list):
            return sorted(str(x) for x in movies)
    except Exception:  # noqa: BLE001
        return []
    return []


@router.get("", response_model=SettingsOut)
async def get_app_settings(
    _: Annotated[dict, Depends(require_auth)],
    db: Session = Depends(get_db),
) -> SettingsOut:
    s = get_settings()
    db_map = _db_map(db)
    _apply_overrides_to_runtime(db_map)
    s = get_settings()
    token = db_map.get("metatube_token", s.metatube_token)
    alist_token = db_map.get("alist_token", s.alist_token)
    extra = {k: v for k, v in db_map.items() if k not in OVERRIDE_KEYS}
    provider = db_map.get("metatube_provider", s.metatube_provider)
    fallback_raw = db_map.get("metatube_fallback")
    fallback = (
        fallback_raw.lower() in ("1", "true", "yes", "on") if fallback_raw is not None else s.metatube_fallback
    )
    return SettingsOut(
        metatube_base_url=db_map.get("metatube_base_url") or s.metatube_base_url,
        metatube_token_set=bool(token),
        metatube_provider=provider or "",
        metatube_fallback=fallback,
        alist_base_url=db_map.get("alist_base_url") or s.alist_base_url,
        alist_token_set=bool(alist_token),
        media_root=str(s.media_root_path),
        auto_scrape=s.auto_scrape,
        scan_extensions=s.scan_extensions,
        cors_origins=s.cors_origins,
        auth_enabled=s.auth_enabled,
        movie_providers=await _providers(),
        extra=extra,
    )


@router.put("", response_model=SettingsOut)
async def update_app_settings(
    body: SettingsUpdate,
    user: Annotated[dict, Depends(require_auth)],
    db: Session = Depends(get_db),
) -> SettingsOut:
    data = body.model_dump(exclude_unset=True)
    extra = data.pop("extra", None)
    for key, value in data.items():
        if value is None:
            continue
        store_val = str(value).lower() if isinstance(value, bool) else str(value)
        row = db.get(AppSetting, key)
        if row is None:
            row = AppSetting(key=key, value=store_val)
        else:
            row.value = store_val
        db.add(row)
    if extra:
        for k, v in extra.items():
            row = db.get(AppSetting, k)
            if row is None:
                row = AppSetting(key=k, value=str(v))
            else:
                row.value = str(v)
            db.add(row)
    db.commit()
    _apply_overrides_to_runtime(_db_map(db))
    return await get_app_settings(user, db)


@router.get("/providers")
async def list_movie_providers(
    _: Annotated[dict, Depends(require_auth)],
) -> dict[str, Any]:
    data = await MetaTubeClient().list_providers()
    return data
