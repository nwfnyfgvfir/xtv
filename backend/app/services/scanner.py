from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models import Library, MediaItem
from app.services.jobs import ScanJob, job_store
from app.services.naming import extract_number
from app.services.scrape import scrape_media_item
from app.services.strm import classify_strm_target, read_strm_target

logger = logging.getLogger(__name__)


def resolve_library_path(lib: Library) -> Path:
    settings = get_settings()
    p = Path(lib.path)
    if not p.is_absolute():
        p = settings.media_root_path / p
    return p.resolve()


def scan_library_sync(db: Session, lib: Library, job: ScanJob | None = None) -> ScanJob:
    settings = get_settings()
    root = resolve_library_path(lib)
    if job is None:
        job = job_store.create(lib.id)
    job.status = "running"
    job.library_id = lib.id

    if not root.exists():
        # Do not prune when the library root is missing — avoid wiping the DB on mount glitches.
        job.status = "error"
        job.message = f"Path not found: {root}"
        job.errors.append(job.message)
        return job

    exts = settings.extension_set
    seen_paths: set[str] = set()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        ext = path.suffix.lower().lstrip(".")
        if ext not in exts:
            continue
        try:
            item = _ingest_file(db, lib, path, job, auto_scrape=False)
            seen_paths.add(item.path)
            job.scanned += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("ingest failed %s", path)
            job.errors.append(f"{path.name}: {exc}")

    # Remove DB rows for files that disappeared from disk.
    existing = db.query(MediaItem).filter(MediaItem.library_id == lib.id).all()
    for item in existing:
        if item.path not in seen_paths:
            db.delete(item)
            job.removed += 1

    db.commit()

    job.message = (
        f"scanning done scanned={job.scanned} created={job.created} "
        f"removed={job.removed}; scraping…"
    )
    if settings.auto_scrape:
        items = (
            db.query(MediaItem)
            .filter(MediaItem.library_id == lib.id, MediaItem.number.isnot(None), MediaItem.scraped_at.is_(None))
            .all()
        )
        total_scrape = len(items)
        for idx, item in enumerate(items, start=1):
            try:
                job.message = f"scraping {idx}/{total_scrape}: {item.number}"
                ok = asyncio.run(scrape_media_item(db, item, force=False))
                if ok:
                    job.scraped += 1
            except Exception as exc:  # noqa: BLE001
                job.errors.append(f"scrape {item.number}: {exc}")

    job.status = "done"
    job.message = (
        f"scanned={job.scanned} created={job.created} "
        f"removed={job.removed} scraped={job.scraped}"
    )
    return job


def _ingest_file(db: Session, lib: Library, path: Path, job: ScanJob, auto_scrape: bool) -> MediaItem:
    abs_path = str(path.resolve())
    existing = (
        db.query(MediaItem)
        .filter(MediaItem.library_id == lib.id, MediaItem.path == abs_path)
        .one_or_none()
    )
    parsed = extract_number(path.name)
    size = path.stat().st_size if path.exists() else None

    source_type = "local"
    strm_target = None
    if path.suffix.lower() == ".strm":
        strm_target = read_strm_target(path)
        source_type = classify_strm_target(strm_target) if strm_target else "strm"

    if existing is None:
        item = MediaItem(
            library_id=lib.id,
            path=abs_path,
            filename=path.name,
            number=parsed.number,
            title=parsed.number or path.stem,
            source_type=source_type,
            strm_target=strm_target,
            disc=parsed.disc,
            subtitle_flag=parsed.subtitle_flag,
            file_size=size,
        )
        db.add(item)
        db.flush()
        job.created += 1
    else:
        item = existing
        item.filename = path.name
        item.number = parsed.number or item.number
        item.disc = parsed.disc or item.disc
        item.subtitle_flag = parsed.subtitle_flag or item.subtitle_flag
        item.file_size = size
        item.source_type = source_type
        item.strm_target = strm_target
        if not item.title:
            item.title = parsed.number or path.stem
        db.add(item)
        db.flush()

    if auto_scrape and item.number and not item.scraped_at:
        asyncio.run(scrape_media_item(db, item, force=False))
        job.scraped += 1

    return item


def run_scan_job(job_id: str, library_id: int) -> None:
    job = job_store.get(job_id)
    if not job:
        return
    db = SessionLocal()
    try:
        lib = db.get(Library, library_id)
        if not lib:
            job.status = "error"
            job.message = "library not found"
            return
        scan_library_sync(db, lib, job)
    except Exception as exc:  # noqa: BLE001
        logger.exception("scan job failed")
        job.status = "error"
        job.message = str(exc)
        job.errors.append(str(exc))
    finally:
        db.close()
