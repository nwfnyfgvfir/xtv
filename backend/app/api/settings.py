from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import AppSetting
from app.schemas import SettingsOut, SettingsUpdate

router = APIRouter()

# Keys that can override env via DB
OVERRIDE_KEYS = {
    "metatube_base_url",
    "metatube_token",
    "alist_base_url",
    "alist_token",
    "auto_scrape",
    "scan_extensions",
}


def _db_map(db: Session) -> dict[str, str]:
    rows = db.query(AppSetting).all()
    return {r.key: r.value for r in rows}


def _apply_overrides_to_runtime(db_map: dict[str, str]) -> None:
    """Mutate cached settings for current process."""
    s = get_settings()
    if "metatube_base_url" in db_map and db_map["metatube_base_url"]:
        s.metatube_base_url = db_map["metatube_base_url"]
    if "metatube_token" in db_map:
        s.metatube_token = db_map["metatube_token"]
    if "alist_base_url" in db_map and db_map["alist_base_url"]:
        s.alist_base_url = db_map["alist_base_url"]
    if "alist_token" in db_map:
        s.alist_token = db_map["alist_token"]
    if "auto_scrape" in db_map:
        s.auto_scrape = db_map["auto_scrape"].lower() in ("1", "true", "yes", "on")
    if "scan_extensions" in db_map and db_map["scan_extensions"]:
        s.scan_extensions = db_map["scan_extensions"]


@router.get("", response_model=SettingsOut)
def get_app_settings(db: Session = Depends(get_db)) -> SettingsOut:
    s = get_settings()
    db_map = _db_map(db)
    _apply_overrides_to_runtime(db_map)
    s = get_settings()
    token = db_map.get("metatube_token", s.metatube_token)
    alist_token = db_map.get("alist_token", s.alist_token)
    extra = {k: v for k, v in db_map.items() if k not in OVERRIDE_KEYS}
    return SettingsOut(
        metatube_base_url=db_map.get("metatube_base_url") or s.metatube_base_url,
        metatube_token_set=bool(token),
        alist_base_url=db_map.get("alist_base_url") or s.alist_base_url,
        alist_token_set=bool(alist_token),
        media_root=str(s.media_root_path),
        auto_scrape=s.auto_scrape,
        scan_extensions=s.scan_extensions,
        cors_origins=s.cors_origins,
        extra=extra,
    )


@router.put("", response_model=SettingsOut)
def update_app_settings(body: SettingsUpdate, db: Session = Depends(get_db)) -> SettingsOut:
    data = body.model_dump(exclude_unset=True)
    extra = data.pop("extra", None)
    for key, value in data.items():
        if value is None:
            continue
        if key not in OVERRIDE_KEYS and key != "metatube_token" and key != "alist_token":
            # all dumped keys are allowed overrides
            pass
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
    return get_app_settings(db)
