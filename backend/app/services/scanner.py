from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models import Library, MediaItem
from app.services.actors import delete_orphan_actors
from app.services.jobs import ScanJob, job_store
from app.services.library_revision import bump_revision
from app.services.naming import extract_number
from app.services.scrape import scrape_media_item
from app.services.strm import read_strm_target

logger = logging.getLogger(__name__)


def resolve_library_path(lib: Library) -> Path:
    settings = get_settings()
    p = Path(lib.path)
    if not p.is_absolute():
        p = settings.media_root_path / p
    return p.resolve()


def _is_media_file(path: Path, exts: set[str]) -> bool:
    if not path.is_file():
        return False
    ext = path.suffix.lower().lstrip(".")
    return bool(ext) and ext in exts


def _normalize_abs(path: Path | str) -> str:
    return str(Path(path).resolve())


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

    if job.removed:
        db.flush()
        delete_orphan_actors(db)

    db.commit()
    if job.created or job.removed:
        bump_revision(lib.id)

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
        scraped_before = job.scraped
        for idx, item in enumerate(items, start=1):
            try:
                job.message = f"scraping {idx}/{total_scrape}: {item.number}"
                ok = asyncio.run(scrape_media_item(db, item, force=False))
                if ok:
                    job.scraped += 1
            except Exception as exc:  # noqa: BLE001
                job.errors.append(f"scrape {item.number}: {exc}")
        # Cover/metadata updates should also nudge clients.
        if job.scraped > scraped_before:
            bump_revision(lib.id)

    job.status = "done"
    job.message = (
        f"scanned={job.scanned} created={job.created} "
        f"removed={job.removed} scraped={job.scraped}"
    )
    return job


def ingest_path(library_id: int, path: str | Path, *, scrape: bool | None = None) -> dict:
    """Ingest a single media file into the library (Jellyfin-style path refresh)."""
    settings = get_settings()
    p = Path(path)
    result = {"ok": False, "created": 0, "scanned": 0, "scraped": 0, "message": ""}
    if not p.exists() or not p.is_file():
        result["message"] = "not a file"
        return result
    if not _is_media_file(p, settings.extension_set):
        result["message"] = "not media"
        return result

    db = SessionLocal()
    try:
        lib = db.get(Library, library_id)
        if not lib:
            result["message"] = "library not found"
            return result
        job = ScanJob(job_id="path", library_id=library_id)
        do_scrape = settings.auto_scrape if scrape is None else scrape
        _ingest_file(db, lib, p, job, auto_scrape=do_scrape)
        db.commit()
        if job.created or job.scraped:
            bump_revision(library_id)
        result.update(
            ok=True,
            created=job.created,
            scanned=1,
            scraped=job.scraped,
            message="ingested",
        )
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("ingest_path failed %s", path)
        db.rollback()
        result["message"] = str(exc)
        return result
    finally:
        db.close()


def remove_path(library_id: int, path: str | Path) -> dict:
    """Remove DB row for a path that no longer exists on disk."""
    abs_path = _normalize_abs(path)
    result = {"ok": False, "removed": 0, "message": ""}
    # If file still exists, do not remove.
    if Path(abs_path).exists():
        result["message"] = "still exists"
        return result

    db = SessionLocal()
    try:
        q = db.query(MediaItem).filter(MediaItem.library_id == library_id, MediaItem.path == abs_path)
        n = q.delete(synchronize_session=False)
        # Also try unresolved / alternate path forms
        if n == 0:
            n = (
                db.query(MediaItem)
                .filter(MediaItem.library_id == library_id, MediaItem.path == str(path))
                .delete(synchronize_session=False)
            )
        if n:
            delete_orphan_actors(db)
        db.commit()
        if n:
            bump_revision(library_id)
        result.update(ok=True, removed=int(n), message="removed" if n else "not found")
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("remove_path failed %s", path)
        db.rollback()
        result["message"] = str(exc)
        return result
    finally:
        db.close()


def refresh_paths(library_id: int, paths: list[str] | set[str]) -> dict:
    """
    Targeted refresh for a small set of paths (files and/or directories).
    Directory paths: rglob media under them and prune DB rows under that prefix.
    """
    settings = get_settings()
    exts = settings.extension_set
    summary = {
        "ok": True,
        "scanned": 0,
        "created": 0,
        "removed": 0,
        "scraped": 0,
        "errors": [],
    }
    if not paths:
        return summary

    db = SessionLocal()
    try:
        lib = db.get(Library, library_id)
        if not lib:
            summary["ok"] = False
            summary["errors"].append("library not found")
            return summary
        root = resolve_library_path(lib)
        root_s = str(root)
        job = ScanJob(job_id="paths", library_id=library_id)

        file_targets: list[Path] = []
        dir_targets: list[Path] = []
        missing: list[str] = []

        for raw in paths:
            p = Path(raw)
            try:
                p = p.resolve()
            except Exception:  # noqa: BLE001
                p = Path(raw)
            # Only touch paths inside the library root.
            try:
                p.relative_to(root)
            except ValueError:
                # Allow if raw string still under root_s prefix (Windows case quirks)
                if not str(p).lower().startswith(root_s.lower()):
                    continue
            if p.exists() and p.is_dir():
                dir_targets.append(p)
            elif p.exists() and p.is_file():
                if _is_media_file(p, exts):
                    file_targets.append(p)
            else:
                missing.append(str(p))

        # Ingest files
        for p in file_targets:
            try:
                _ingest_file(db, lib, p, job, auto_scrape=False)
                job.scanned += 1
            except Exception as exc:  # noqa: BLE001
                logger.exception("refresh ingest failed %s", p)
                summary["errors"].append(f"{p.name}: {exc}")

        # Directory subtrees: ingest + prefix prune
        for d in dir_targets:
            seen: set[str] = set()
            try:
                for path in d.rglob("*"):
                    if not _is_media_file(path, exts):
                        continue
                    try:
                        item = _ingest_file(db, lib, path, job, auto_scrape=False)
                        seen.add(item.path)
                        job.scanned += 1
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("refresh dir ingest failed %s", path)
                        summary["errors"].append(f"{path.name}: {exc}")
                prefix = str(d.resolve())
                # Normalize prefix separator for SQL LIKE
                rows = (
                    db.query(MediaItem)
                    .filter(MediaItem.library_id == library_id, MediaItem.path.like(prefix + "%"))
                    .all()
                )
                for item in rows:
                    if item.path not in seen:
                        # Only prune if truly under this dir and missing on disk
                        if not Path(item.path).exists():
                            db.delete(item)
                            job.removed += 1
            except Exception as exc:  # noqa: BLE001
                logger.exception("refresh dir failed %s", d)
                summary["errors"].append(f"{d}: {exc}")

        # Explicit missing paths → remove
        for m in missing:
            candidates = {m}
            try:
                candidates.add(_normalize_abs(m))
            except Exception:  # noqa: BLE001
                pass
            n = 0
            for cand in candidates:
                n = (
                    db.query(MediaItem)
                    .filter(MediaItem.library_id == library_id, MediaItem.path == cand)
                    .delete(synchronize_session=False)
                )
                if n:
                    break
            job.removed += int(n)

        if job.removed:
            delete_orphan_actors(db)
        db.commit()

        # Optional scrape for newly created items only
        if settings.auto_scrape and job.created:
            items = (
                db.query(MediaItem)
                .filter(
                    MediaItem.library_id == library_id,
                    MediaItem.number.isnot(None),
                    MediaItem.scraped_at.is_(None),
                )
                .order_by(MediaItem.id.desc())
                .limit(max(job.created * 2, 10))
                .all()
            )
            for item in items:
                try:
                    ok = asyncio.run(scrape_media_item(db, item, force=False))
                    if ok:
                        job.scraped += 1
                except Exception as exc:  # noqa: BLE001
                    summary["errors"].append(f"scrape {item.number}: {exc}")

        if job.created or job.removed or job.scraped:
            bump_revision(library_id)

        summary.update(
            scanned=job.scanned,
            created=job.created,
            removed=job.removed,
            scraped=job.scraped,
        )
        return summary
    except Exception as exc:  # noqa: BLE001
        logger.exception("refresh_paths failed library=%s", library_id)
        db.rollback()
        summary["ok"] = False
        summary["errors"].append(str(exc))
        return summary
    finally:
        db.close()


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
        source_type = "strm"

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


def run_rescrape_pending_job(job_id: str, library_id: int) -> None:
    """Background: scrape all unscraped items that have a number in the library."""
    job = job_store.get(job_id)
    if not job:
        return
    job.status = "running"
    job.library_id = library_id
    db = SessionLocal()
    try:
        lib = db.get(Library, library_id)
        if not lib:
            job.status = "error"
            job.message = "library not found"
            job.errors.append(job.message)
            return

        items = (
            db.query(MediaItem)
            .filter(
                MediaItem.library_id == library_id,
                MediaItem.number.isnot(None),
                MediaItem.scraped_at.is_(None),
            )
            .order_by(MediaItem.id.asc())
            .all()
        )
        total = len(items)
        job.scanned = total
        if total == 0:
            job.status = "done"
            job.message = "no pending items (need number + unscraped)"
            return

        scraped_ok = 0
        for idx, item in enumerate(items, start=1):
            number = item.number or "?"
            job.message = f"scraping {idx}/{total}: {number}"
            try:
                ok = asyncio.run(scrape_media_item(db, item, force=False))
                if ok:
                    scraped_ok += 1
                    job.scraped = scraped_ok
            except Exception as exc:  # noqa: BLE001
                logger.exception("pending scrape failed %s", number)
                job.errors.append(f"scrape {number}: {exc}")

        if scraped_ok:
            bump_revision(library_id)

        job.status = "done"
        job.scraped = scraped_ok
        job.message = f"pending scrape done: scraped={scraped_ok}/{total}"
    except Exception as exc:  # noqa: BLE001
        logger.exception("rescrape pending job failed")
        job.status = "error"
        job.message = str(exc)
        job.errors.append(str(exc))
    finally:
        db.close()
