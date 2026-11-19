from __future__ import annotations

import hashlib
import json
import logging
from time import perf_counter
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal, get_db
from app.deps import require_auth
from app.models import AppSetting
from app.schemas import ScraperTestIn, ScraperTestOut, SettingsOut, SettingsUpdate
from app.services.metatube import MetaTubeClient, MetaTubeError, parse_movie_provider_names
from app.services.scrape import preview_scraper
from app.services.stash import StashClient, StashError
from app.services.images import remote_proxy_template_error, normalize_site_image_base_url

router = APIRouter()
logger = logging.getLogger(__name__)

_PROVIDERS_CACHE_KEY = "metatube_movie_providers_cache"
_STASH_CACHE_PREFIX = "stash_scrapers_cache:"
_RETIRED_SCRAPER_CACHE_PREFIX = "stashscrapers_catalog_cache:"
_SCRAPER_CACHE_PREFIXES = (_STASH_CACHE_PREFIX, _RETIRED_SCRAPER_CACHE_PREFIX)
_MAX_PRIORITY = 50
_MAX_PROVIDER_NAME_LEN = 64
_MAX_STASH_SCRAPER_ID_LEN = 256

OVERRIDE_KEYS = {
    "task_concurrency",
    "scrape_source",
    "scrape_source_priority",
    "stash_base_url",
    "stash_api_key",
    "stash_scraper",
    "stash_scraper_priority",
    "stash_fallback",
    "metatube_base_url",
    "metatube_token",
    "metatube_provider",
    "metatube_provider_priority",
    "metatube_fallback",
    "auto_scrape",
    "auto_translate",
    "translate_provider",
    "translate_google_proxy",
    "translate_google_proxy_url",
    "translate_deepl_api_key",
    "translate_deepl_api_url",
    "translate_deepl_free",
    "translate_deepl_proxy",
    "translate_deepl_proxy_url",
    "translate_ai_api_url",
    "translate_ai_api_key",
    "translate_ai_model",
    "image_proxy_mode",
    "image_external_proxy_url",
    "image_site_base_url",
    "scan_extensions",
}
_RETIRED_SOURCE_SETTINGS = frozenset({
    "stashscrapers_base_url",
    "stashscrapers_token",
    "stashscrapers_scraper",
    "stashscrapers_scraper_priority",
    "stashscrapers_fallback",
})

_BOOL_TRUE = ("1", "true", "yes", "on")
_IMAGE_PROXY_MODES = frozenset({"site", "external"})
_RETIRED_IMAGE_SETTINGS = frozenset({'image_local_cache', 'image_cache_max_mb'})
_TRANSLATE_PROVIDERS = frozenset({"google", "bing", "deepl", "ai"})


def _db_map(db: Session) -> dict[str, str]:
    rows = db.query(AppSetting).all()
    return {r.key: r.value for r in rows if r.key not in _RETIRED_IMAGE_SETTINGS}


def parse_priority_list(raw: str | list[str] | None, *, max_name_len: int = _MAX_PROVIDER_NAME_LEN) -> list[str]:
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
        if not name or len(name) > max_name_len or name in seen:
            continue
        seen.add(name)
        out.append(name)
        if len(out) >= _MAX_PRIORITY:
            break
    return out


def _sanitize_priority(value: list[Any] | None, *, max_name_len: int = _MAX_PROVIDER_NAME_LEN) -> list[str]:
    if not value:
        return []
    return parse_priority_list(value, max_name_len=max_name_len)


def apply_persisted_overrides() -> None:
    """Apply DB-stored settings onto the runtime Settings object.

    Must be called at startup. Without it, a restart silently ignores every
    setting the user saved in the UI (scrape provider priority, translate
    engine, image proxy…) until something happens to hit GET/PUT /api/settings
    — which for a headless scan never happens.
    """
    db = SessionLocal()
    try:
        _apply_overrides_to_runtime(_db_map(db))
    except Exception:  # noqa: BLE001
        logger.exception("Failed to apply persisted settings overrides")
    finally:
        db.close()


def _apply_overrides_to_runtime(db_map: dict[str, str]) -> None:
    if "task_concurrency" in db_map:
        try:
            get_settings().task_concurrency = max(1, min(8, int(db_map["task_concurrency"])))
        except ValueError:
            pass
    s = get_settings()
    if db_map.get("scrape_source") in {"metatube", "stash"}:
        s.scrape_source = db_map["scrape_source"]
    elif s.scrape_source not in {"metatube", "stash"}:
        s.scrape_source = "metatube"
    if "scrape_source_priority" in db_map:
        s.scrape_source_priority = db_map["scrape_source_priority"] or ""
    for key in ("stash_base_url", "stash_api_key", "stash_scraper", "stash_scraper_priority"):
        if key in db_map:
            setattr(s, key, db_map[key] or "")
    if "stash_fallback" in db_map:
        s.stash_fallback = db_map["stash_fallback"].lower() in _BOOL_TRUE
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
    if "translate_google_proxy" in db_map:
        s.translate_google_proxy = db_map["translate_google_proxy"].lower() in _BOOL_TRUE
    if "translate_google_proxy_url" in db_map:
        s.translate_google_proxy_url = db_map["translate_google_proxy_url"] or ""
    if "translate_deepl_api_key" in db_map:
        s.translate_deepl_api_key = db_map["translate_deepl_api_key"]
    if "translate_deepl_api_url" in db_map:
        s.translate_deepl_api_url = db_map["translate_deepl_api_url"] or ""
    if "translate_deepl_free" in db_map:
        s.translate_deepl_free = db_map["translate_deepl_free"].lower() in _BOOL_TRUE
    if "translate_deepl_proxy" in db_map:
        s.translate_deepl_proxy = db_map["translate_deepl_proxy"].lower() in _BOOL_TRUE
    if "translate_deepl_proxy_url" in db_map:
        s.translate_deepl_proxy_url = db_map["translate_deepl_proxy_url"] or ""
    if "translate_ai_api_url" in db_map:
        s.translate_ai_api_url = db_map["translate_ai_api_url"] or ""
    if "translate_ai_api_key" in db_map:
        s.translate_ai_api_key = db_map["translate_ai_api_key"]
    if "translate_ai_model" in db_map:
        s.translate_ai_model = db_map["translate_ai_model"] or ""
    if "image_proxy_mode" in db_map:
        mode = (db_map["image_proxy_mode"] or "").strip().lower()
        s.image_proxy_mode = mode if mode in _IMAGE_PROXY_MODES else 'site'
    if "image_external_proxy_url" in db_map:
        s.image_external_proxy_url = db_map["image_external_proxy_url"] or ""
    if "image_site_base_url" in db_map:
        s.image_site_base_url = normalize_site_image_base_url(db_map["image_site_base_url"] or "")
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


async def _community_providers_with_status(db: Session) -> tuple[list[str], dict[str, str], str | None, bool]:
    s = get_settings()
    base, token = s.stash_base_url, s.stash_api_key
    fingerprint = hashlib.sha256(f"{base}\0{token}".encode()).hexdigest()
    cache_key = f"{_STASH_CACHE_PREFIX}{fingerprint}"
    try:
        client = StashClient(s)
        scrapers = await client.list_scrapers()
        labels = {
            row["id"]: row["name"] + ("（仅 URL）" if not {"NAME", "FRAGMENT"}.intersection(row["types"]) else "")
            for row in scrapers
        }
    except Exception as exc:  # noqa: BLE001
        error = str(exc)[:300] or "Community scrapers unavailable"
        row = db.get(AppSetting, cache_key)
        labels = {}
        if row:
            try:
                data = json.loads(row.value)
                if isinstance(data, dict):
                    labels = {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}
            except ValueError:
                pass
        return list(labels), labels, error, bool(labels)
    try:
        row = db.get(AppSetting, cache_key) or AppSetting(key=cache_key, value="")
        row.value = json.dumps(labels, ensure_ascii=False)
        db.add(row)
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.debug("Failed to cache community scrapers", exc_info=True)
    return list(labels), labels, None, False


async def _stash_providers_with_status(db: Session) -> tuple[list[str], dict[str, str], str | None, bool]:
    return await _community_providers_with_status(db)


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
        if k not in OVERRIDE_KEYS and k not in _RETIRED_SOURCE_SETTINGS
        and k != _PROVIDERS_CACHE_KEY and not k.startswith(_SCRAPER_CACHE_PREFIXES)
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
    google_proxy_raw = db_map.get("translate_google_proxy")
    translate_google_proxy = (
        google_proxy_raw.lower() in _BOOL_TRUE
        if google_proxy_raw is not None
        else bool(s.translate_google_proxy)
    )
    translate_google_proxy_url = (
        db_map.get("translate_google_proxy_url", s.translate_google_proxy_url) or ""
    )
    deepl_key = db_map.get("translate_deepl_api_key", s.translate_deepl_api_key)
    translate_deepl_api_url = (
        db_map.get("translate_deepl_api_url", s.translate_deepl_api_url) or ""
    )
    deepl_free_raw = db_map.get("translate_deepl_free")
    translate_deepl_free = (
        deepl_free_raw.lower() in _BOOL_TRUE
        if deepl_free_raw is not None
        else bool(s.translate_deepl_free)
    )
    deepl_proxy_raw = db_map.get("translate_deepl_proxy")
    translate_deepl_proxy = (
        deepl_proxy_raw.lower() in _BOOL_TRUE
        if deepl_proxy_raw is not None
        else bool(s.translate_deepl_proxy)
    )
    translate_deepl_proxy_url = (
        db_map.get("translate_deepl_proxy_url", s.translate_deepl_proxy_url) or ""
    )
    mode_raw = (db_map.get("image_proxy_mode") or s.image_proxy_mode or "site").strip().lower()
    image_proxy_mode = mode_raw if mode_raw in _IMAGE_PROXY_MODES else "site"
    labels: dict[str, str] = {}
    source = s.scrape_source if s.scrape_source == "stash" else "metatube"
    if source == "stash":
        movie_providers, labels, providers_error, from_cache = await _stash_providers_with_status(db)
    else:
        movie_providers, providers_error, from_cache = await _providers_with_status(db)
    return SettingsOut(
        task_concurrency=s.task_concurrency,
        scrape_source=source,
        scrape_source_priority=[name for name in parse_priority_list(s.scrape_source_priority)
            if name in {"metatube", "stash"}],
        stash_base_url=s.stash_base_url,
        stash_api_key_set=bool(s.stash_api_key.strip()),
        stash_scraper=s.stash_scraper,
        stash_scraper_priority=parse_priority_list(s.stash_scraper_priority, max_name_len=_MAX_STASH_SCRAPER_ID_LEN),
        stash_fallback=s.stash_fallback,
        metatube_base_url=db_map.get("metatube_base_url") or s.metatube_base_url,
        metatube_token_set=bool(token),
        metatube_provider=provider or "",
        metatube_provider_priority=priority,
        metatube_fallback=fallback,
        media_root=str(s.media_root_path),
        auto_scrape=s.auto_scrape,
        auto_translate=auto_translate,
        translate_provider=translate_provider,  # type: ignore[arg-type]
        translate_google_proxy=translate_google_proxy,
        translate_google_proxy_url=translate_google_proxy_url,
        translate_deepl_api_key_set=bool(deepl_key),
        translate_deepl_api_url=translate_deepl_api_url,
        translate_deepl_free=translate_deepl_free,
        translate_deepl_proxy=translate_deepl_proxy,
        translate_deepl_proxy_url=translate_deepl_proxy_url,
        translate_ai_api_url=s.translate_ai_api_url,
        translate_ai_api_key_set=bool(s.translate_ai_api_key.strip()),
        translate_ai_model=s.translate_ai_model,
        image_proxy_mode=image_proxy_mode,  # type: ignore[arg-type]
        image_external_proxy_url=db_map.get("image_external_proxy_url", s.image_external_proxy_url)
        or "",
        image_site_base_url=db_map.get("image_site_base_url", s.image_site_base_url) or "",
        scan_extensions=s.scan_extensions,
        cors_origins=s.cors_origins,
        auth_enabled=s.auth_enabled,
        movie_providers=movie_providers,
        movie_provider_labels=labels,
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
    if extra and 'image_site_base_url' in extra:
        data.setdefault('image_site_base_url', extra.pop('image_site_base_url'))
    if data.get('image_site_base_url') is not None:
        try:
            data['image_site_base_url'] = normalize_site_image_base_url(data['image_site_base_url'])
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    if {'image_proxy_mode', 'image_external_proxy_url'}.intersection(data):
        saved = _db_map(db)
        runtime = get_settings()
        mode = data.get('image_proxy_mode') or saved.get('image_proxy_mode') or runtime.image_proxy_mode
        template = data.get('image_external_proxy_url')
        if template is None:
            template = saved.get('image_external_proxy_url', runtime.image_external_proxy_url)
        if mode == 'external' and (error := remote_proxy_template_error(template)):
            raise HTTPException(422, error)
    for key, value in data.items():
        if value is None:
            continue
        if key in {"scrape_source_priority", "metatube_provider_priority", "stash_scraper_priority"}:
            max_length = _MAX_PROVIDER_NAME_LEN if key == "metatube_provider_priority" else _MAX_STASH_SCRAPER_ID_LEN
            store_val = json.dumps(
                _sanitize_priority(value if isinstance(value, list) else [], max_name_len=max_length),
                ensure_ascii=False,
            )
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
            if k in _RETIRED_IMAGE_SETTINGS or k in _RETIRED_SOURCE_SETTINGS or k == _PROVIDERS_CACHE_KEY or k.startswith(_SCRAPER_CACHE_PREFIXES):
                continue
            row = db.get(AppSetting, k)
            if row is None:
                row = AppSetting(key=k, value=str(v))
            else:
                row.value = str(v)
            db.add(row)
    db.commit()
    _apply_overrides_to_runtime(_db_map(db))
    if {'image_proxy_mode', 'image_external_proxy_url'}.intersection(data):
        from app.models import ImageBackup, utcnow
        from app.services.image_backups import worker
        db.query(ImageBackup).filter_by(status='pending').update({'retry_at': utcnow()})
        db.commit()
        worker.notify()
    if 'task_concurrency' in data:
        from app.services.task_store import wakeup
        wakeup.set()
    return await get_app_settings(user, db)


@router.post("/test-scraper", response_model=ScraperTestOut)
async def test_scraper(
    body: ScraperTestIn,
    _: Annotated[dict, Depends(require_auth)],
) -> ScraperTestOut:
    settings = get_settings().model_copy(update={"scrape_source": body.source})
    if body.source == "metatube" and not settings.metatube_token.strip():
        raise HTTPException(400, "Configure a MetaTube token before testing this scraper")
    started = perf_counter()
    try:
        result = await preview_scraper(settings, body.query, body.provider)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except (MetaTubeError, StashError) as exc:
        raise HTTPException(502, str(exc) or "Scraper test failed") from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected scraper test failure")
        raise HTTPException(502, "Scraper test failed unexpectedly") from exc
    return ScraperTestOut(
        matched=result is not None,
        source=body.source,
        elapsed_ms=max(0, round((perf_counter() - started) * 1000)),
        result=result,
    )


@router.get("/providers")
async def list_movie_providers(
    _: Annotated[dict, Depends(require_auth)],
    db: Session = Depends(get_db),
    source: Literal["metatube", "stash"] | None = None,
) -> dict[str, Any]:
    source = source or get_settings().scrape_source
    if source == "stash":
        names, labels, error, from_cache = await _stash_providers_with_status(db)
        if error and not from_cache:
            raise HTTPException(502, error)
        return {
            "movie_providers": names, "movie_provider_labels": labels,
            "count": len(names), "from_cache": from_cache, "error": error,
        }
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
