from __future__ import annotations

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import require_auth
from app.models import AppSetting
from app.schemas import SettingsOut, SettingsUpdate
from app.services.metatube import MetaTubeClient, MetaTubeError, parse_movie_provider_names

router = APIRouter()
logger = logging.getLogger(__name__)

_PROVIDERS_CACHE_KEY = "metatube_movie_providers_cache"
_MAX_PRIORITY = 50
_MAX_PROVIDER_NAME_LEN = 64

OVERRIDE_KEYS = {
    "metatube_base_url",
    "metatube_token",
    "metatube_provider",
    "metatube_provider_priority",
    "metatube_fallback",
    "auto_scrape",
    "auto_translate",
    "translate_provider",
    "image_proxy_mode",
    "image_external_proxy_url",
    "image_local_cache",
    "scan_extensions",
}

_BOOL_TRUE = ("1", "true", "yes", "on")
_IMAGE_PROXY_MODES = frozenset({"site", "metatube", "external"})
_TRANSLATE_PROVIDERS = frozenset({"google", "bing"})


def _db_map(db: Session) -> dict[str, str]:
    rows = db.query(AppSetting).all()
    return {r.key: r.value for r in rows}


def parse_priority_list(raw: str | list[str] | None) -> list[str]:
    """Parse provider priority from JSON string or list; invalid → []."""
    if raw is None:
        return []
    if isinstance(raw, list):
        data = raw
    else:
        text = str(raw).strip()
        if not text:
            return []
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return []
    if not isinstance(data, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in data:
        name = str(item).strip()
        if not name or len(name) > _MAX_PROVIDER_NAME_LEN or name in seen:
            continue
        seen.add(name)
        out.append(name)
        if len(out) >= _MAX_PRIORITY:
            break
    return out


def _sanitize_priority(value: list[Any] | None) -> list[str]:
    if not value:
        return []
    return parse_priority_list(value)


def _apply_overrides_to_runtime(db_map: dict[str, str]) -> None:
    s = get_settings()
    if "metatube_base_url" in db_map and db_map["metatube_base_url"]:
        s.metatube_base_url = db_map["metatube_base_url"]
    if "metatube_token" in db_map:
        s.metatube_token = db_map["metatube_token"]
    if "metatube_provider" in db_map:
        s.metatube_provider = db_map["metatube_provider"]
    if "metatube_provider_priority" in db_map:
        s.metatube_provider_priority = db_map["metatube_provider_priority"] or ""
    if "metatube_fallback" in db_map:
        s.metatube_fallback = db_map["metatube_fallback"].lower() in _BOOL_TRUE
    if "auto_scrape" in db_map:
        s.auto_scrape = db_map["auto_scrape"].lower() in _BOOL_TRUE
    if "auto_translate" in db_map:
        s.auto_translate = db_map["auto_translate"].lower() in _BOOL_TRUE
    if "translate_provider" in db_map:
        provider = (db_map["translate_provider"] or "").strip().lower()
        if provider in _TRANSLATE_PROVIDERS:
            s.translate_provider = provider
    if "image_proxy_mode" in db_map:
        mode = (db_map["image_proxy_mode"] or "").strip().lower()
        if mode in _IMAGE_PROXY_MODES:
            s.image_proxy_mode = mode
    if "image_external_proxy_url" in db_map:
        s.image_external_proxy_url = db_map["image_external_proxy_url"] or ""
    if "image_local_cache" in db_map:
        s.image_local_cache = db_map["image_local_cache"].lower() in _BOOL_TRUE
    if "scan_extensions" in db_map and db_map["scan_extensions"]:
        s.scan_extensions = db_map["scan_extensions"]


def _load_providers_cache(db: Session) -> list[str]:
    row = db.get(AppSetting, _PROVIDERS_CACHE_KEY)
    if not row or not row.value:
        return []
    try:
        data = json.loads(row.value)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(x).strip() for x in data if str(x).strip()]


def _save_providers_cache(db: Session, names: list[str]) -> None:
    payload = json.dumps(names, ensure_ascii=False)
    row = db.get(AppSetting, _PROVIDERS_CACHE_KEY)
    if row is None:
        row = AppSetting(key=_PROVIDERS_CACHE_KEY, value=payload)
    else:
        row.value = payload
    db.add(row)
    db.commit()


async def _providers_with_status(db: Session) -> tuple[list[str], str | None, bool]:
    """Return (names, error, from_cache)."""
    try:
        data = await MetaTubeClient().list_providers()
        names = parse_movie_provider_names(data)
        if names:
            try:
                _save_providers_cache(db, names)
            except Exception:  # noqa: BLE001
                logger.debug("failed to cache movie providers", exc_info=True)
        return names, None, False
    except Exception as exc:  # noqa: BLE001
        err = str(exc)[:200] or "MetaTube providers unavailable"
        logger.warning("list movie providers failed: %s", err)
        cached = _load_providers_cache(db)
        if cached:
            return cached, err, True
        return [], err, False


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
    extra = {
        k: v
        for k, v in db_map.items()
        if k not in OVERRIDE_KEYS and k != _PROVIDERS_CACHE_KEY
    }
    provider = db_map.get("metatube_provider", s.metatube_provider)
    priority = parse_priority_list(
        db_map.get("metatube_provider_priority", s.metatube_provider_priority)
    )
    fallback_raw = db_map.get("metatube_fallback")
    fallback = (
        fallback_raw.lower() in _BOOL_TRUE if fallback_raw is not None else s.metatube_fallback
    )
    auto_translate_raw = db_map.get("auto_translate")
    auto_translate = (
        auto_translate_raw.lower() in _BOOL_TRUE
        if auto_translate_raw is not None
        else s.auto_translate
    )
    provider_raw = (
        db_map.get("translate_provider") or s.translate_provider or "google"
    ).strip().lower()
    translate_provider = provider_raw if provider_raw in _TRANSLATE_PROVIDERS else "google"
    mode_raw = (db_map.get("image_proxy_mode") or s.image_proxy_mode or "site").strip().lower()
    image_proxy_mode = mode_raw if mode_raw in _IMAGE_PROXY_MODES else "site"
    local_cache_raw = db_map.get("image_local_cache")
    image_local_cache = (
        local_cache_raw.lower() in _BOOL_TRUE
        if local_cache_raw is not None
        else bool(s.image_local_cache)
    )
    movie_providers, providers_error, from_cache = await _providers_with_status(db)
    return SettingsOut(
        metatube_base_url=db_map.get("metatube_base_url") or s.metatube_base_url,
        metatube_token_set=bool(token),
        metatube_provider=provider or "",
        metatube_provider_priority=priority,
        metatube_fallback=fallback,
        media_root=str(s.media_root_path),
        auto_scrape=s.auto_scrape,
        auto_translate=auto_translate,
        translate_provider=translate_provider,  # type: ignore[arg-type]
        image_proxy_mode=image_proxy_mode,  # type: ignore[arg-type]
        image_external_proxy_url=db_map.get("image_external_proxy_url", s.image_external_proxy_url)
        or "",
        image_local_cache=image_local_cache,
        scan_extensions=s.scan_extensions,
        cors_origins=s.cors_origins,
        auth_enabled=s.auth_enabled,
        movie_providers=movie_providers,
        movie_providers_error=providers_error,
        movie_providers_from_cache=from_cache,
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
        if key == "metatube_provider_priority":
            store_val = json.dumps(_sanitize_priority(value if isinstance(value, list) else []), ensure_ascii=False)
        elif isinstance(value, list):
            store_val = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, bool):
            store_val = str(value).lower()
        else:
            store_val = str(value)
        row = db.get(AppSetting, key)
        if row is None:
            row = AppSetting(key=key, value=store_val)
        else:
            row.value = store_val
        db.add(row)
    if extra:
        for k, v in extra.items():
            if k == _PROVIDERS_CACHE_KEY:
                continue
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
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        data = await MetaTubeClient().list_providers()
    except MetaTubeError as exc:
        raise HTTPException(502, str(exc) or "MetaTube providers unavailable") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"MetaTube providers unavailable: {exc}") from exc
    names = parse_movie_provider_names(data)
    if names:
        try:
            _save_providers_cache(db, names)
        except Exception:  # noqa: BLE001
            logger.debug("failed to cache movie providers", exc_info=True)
    return {
        "data": data,
        "movie_providers": names,
        "count": len(names),
        "from_cache": False,
    }
