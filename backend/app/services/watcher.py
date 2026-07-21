from __future__ import annotations

import logging
import threading
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers.polling import PollingObserver

from app.config import get_settings
from app.db import SessionLocal
from app.models import Library
from app.services.jobs import job_store
from app.services.scanner import (
    refresh_paths,
    resolve_library_path,
    run_scan_job,
)

logger = logging.getLogger(__name__)

_DEBOUNCE_SEC = 2.5
_POLL_INTERVAL = 3.0
# If more than this many distinct paths queue up, fall back to full library scan.
_PATH_STORM_THRESHOLD = 50

_observer: PollingObserver | None = None
_lock = threading.Lock()
# library_id -> pending timer
_timers: dict[int, threading.Timer] = {}
# library_id -> pending affected paths (files/dirs)
_pending_paths: dict[int, set[str]] = {}
# libraries currently scanning from watcher
_scanning: set[int] = set()
_watched_ids: set[int] = set()


def _is_media_path(path: str) -> bool:
    settings = get_settings()
    ext = Path(path).suffix.lower().lstrip(".")
    return bool(ext) and ext in settings.extension_set


def _should_handle(event: FileSystemEvent) -> bool:
    if event.is_directory:
        # Directory create/delete/move can imply many files changed.
        return True
    src = getattr(event, "src_path", "") or ""
    dest = getattr(event, "dest_path", "") or ""
    return _is_media_path(str(src)) or _is_media_path(str(dest))


def _collect_event_paths(event: FileSystemEvent) -> list[str]:
    paths: list[str] = []
    src = getattr(event, "src_path", None)
    dest = getattr(event, "dest_path", None)
    et = getattr(event, "event_type", "") or ""
    if src:
        paths.append(str(src))
    # Renames / moves: both ends matter (remove old, ingest new).
    if dest and str(dest) != str(src):
        paths.append(str(dest))
    # For pure deletes, src is enough (already added).
    _ = et
    return paths


def _run_debounced_refresh(library_id: int) -> None:
    with _lock:
        _timers.pop(library_id, None)
        paths = set(_pending_paths.pop(library_id, set()))
        if library_id in _scanning:
            # Reschedule after current scan finishes; re-queue paths.
            if paths:
                _pending_paths.setdefault(library_id, set()).update(paths)
            t = threading.Timer(_DEBOUNCE_SEC, _run_debounced_refresh, args=[library_id])
            t.daemon = True
            _timers[library_id] = t
            t.start()
            return
        _scanning.add(library_id)

    try:
        if not paths:
            return
        # Path storm or many directory events → full scan (safe prune).
        dir_like = 0
        for p in paths:
            try:
                if Path(p).is_dir():
                    dir_like += 1
            except Exception:  # noqa: BLE001
                pass
        if len(paths) > _PATH_STORM_THRESHOLD or dir_like > 5:
            job = job_store.create(library_id)
            logger.info(
                "Watcher full scan library=%s job=%s paths=%s",
                library_id,
                job.job_id,
                len(paths),
            )
            run_scan_job(job.job_id, library_id)
            logger.info(
                "Watcher full scan finished library=%s status=%s message=%s",
                library_id,
                job.status,
                job.message,
            )
        else:
            logger.info(
                "Watcher path refresh library=%s paths=%s sample=%s",
                library_id,
                len(paths),
                list(paths)[:5],
            )
            summary = refresh_paths(library_id, paths)
            logger.info(
                "Watcher path refresh done library=%s created=%s removed=%s scanned=%s ok=%s",
                library_id,
                summary.get("created"),
                summary.get("removed"),
                summary.get("scanned"),
                summary.get("ok"),
            )
    except Exception:  # noqa: BLE001
        logger.exception("Watcher refresh failed library=%s", library_id)
    finally:
        with _lock:
            _scanning.discard(library_id)


def schedule_library_scan(library_id: int, paths: list[str] | None = None) -> None:
    """Debounce FS events into a targeted path refresh (or full scan on storm)."""
    with _lock:
        if paths:
            bucket = _pending_paths.setdefault(library_id, set())
            for p in paths:
                if p:
                    bucket.add(p)
        existing = _timers.get(library_id)
        if existing is not None:
            existing.cancel()
        t = threading.Timer(_DEBOUNCE_SEC, _run_debounced_refresh, args=[library_id])
        t.daemon = True
        _timers[library_id] = t
        t.start()


class _LibraryHandler(FileSystemEventHandler):
    def __init__(self, library_id: int) -> None:
        super().__init__()
        self.library_id = library_id

    def on_any_event(self, event: FileSystemEvent) -> None:
        if getattr(event, "event_type", "") == "opened":
            return
        if not _should_handle(event):
            return
        paths = _collect_event_paths(event)
        logger.debug(
            "FS event library=%s type=%s paths=%s",
            self.library_id,
            getattr(event, "event_type", "?"),
            paths,
        )
        schedule_library_scan(self.library_id, paths)


def _make_observer() -> PollingObserver:
    # PollingObserver works on Docker Desktop / Windows bind mounts where native
    # inotify/ReadDirectoryChanges often miss host-side creates.
    return PollingObserver(timeout=_POLL_INTERVAL)


def start_watcher() -> None:
    global _observer
    with _lock:
        if _observer is not None:
            return
        _observer = _make_observer()
        _observer.daemon = True
        _observer.start()
    reload_watches()
    logger.info("Filesystem watcher started (PollingObserver interval=%ss)", _POLL_INTERVAL)


def stop_watcher() -> None:
    global _observer
    with _lock:
        for t in _timers.values():
            t.cancel()
        _timers.clear()
        _pending_paths.clear()
        obs = _observer
        _observer = None
        _watched_ids.clear()
    if obs is not None:
        try:
            obs.stop()
            obs.join(timeout=5)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to stop filesystem watcher")
    logger.info("Filesystem watcher stopped")


def reload_watches() -> None:
    """Re-sync observers with all enabled libraries."""
    global _observer
    with _lock:
        if _observer is None:
            return
        # Restart observer to drop old watches cleanly.
        try:
            _observer.stop()
            _observer.join(timeout=5)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to reset observer")
        _observer = _make_observer()
        _observer.daemon = True
        _observer.start()
        _watched_ids.clear()
        for t in _timers.values():
            t.cancel()
        _timers.clear()
        _pending_paths.clear()

        db = SessionLocal()
        try:
            libs = db.query(Library).filter(Library.enabled.is_(True)).all()
            for lib in libs:
                root = resolve_library_path(lib)
                if not root.exists() or not root.is_dir():
                    logger.warning(
                        "Skip watch library=%s path missing or not dir: %s",
                        lib.id,
                        root,
                    )
                    continue
                handler = _LibraryHandler(lib.id)
                try:
                    _observer.schedule(handler, str(root), recursive=True)
                    _watched_ids.add(lib.id)
                    logger.info("Watching library=%s path=%s", lib.id, root)
                except Exception:  # noqa: BLE001
                    logger.exception("Failed to watch library=%s path=%s", lib.id, root)
        finally:
            db.close()


def watcher_status() -> dict:
    with _lock:
        return {
            "running": _observer is not None and _observer.is_alive() if _observer else False,
            "observer_type": type(_observer).__name__ if _observer else None,
            "poll_interval_sec": _POLL_INTERVAL,
            "watched_library_ids": sorted(_watched_ids),
            "pending_scans": sorted(_timers.keys()),
            "pending_path_counts": {k: len(v) for k, v in _pending_paths.items()},
            "scanning": sorted(_scanning),
            "debounce_sec": _DEBOUNCE_SEC,
            "path_storm_threshold": _PATH_STORM_THRESHOLD,
        }
