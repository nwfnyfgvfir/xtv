from __future__ import annotations

import logging
import threading
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from app.config import get_settings
from app.db import SessionLocal
from app.models import Library
from app.services.jobs import job_store
from app.services.scanner import resolve_library_path, run_scan_job

logger = logging.getLogger(__name__)

_DEBOUNCE_SEC = 2.5
_observer: Observer | None = None
_lock = threading.Lock()
# library_id -> pending timer
_timers: dict[int, threading.Timer] = {}
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


def _run_debounced_scan(library_id: int) -> None:
    with _lock:
        _timers.pop(library_id, None)
        if library_id in _scanning:
            # Reschedule after current scan finishes.
            t = threading.Timer(_DEBOUNCE_SEC, _run_debounced_scan, args=[library_id])
            t.daemon = True
            _timers[library_id] = t
            t.start()
            return
        _scanning.add(library_id)

    try:
        job = job_store.create(library_id)
        logger.info("Watcher scan start library=%s job=%s", library_id, job.job_id)
        run_scan_job(job.job_id, library_id)
        logger.info(
            "Watcher scan finished library=%s status=%s message=%s",
            library_id,
            job.status,
            job.message,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Watcher scan failed library=%s", library_id)
    finally:
        with _lock:
            _scanning.discard(library_id)


def schedule_library_scan(library_id: int) -> None:
    """Debounce FS events into a single full scan (with prune)."""
    with _lock:
        existing = _timers.get(library_id)
        if existing is not None:
            existing.cancel()
        t = threading.Timer(_DEBOUNCE_SEC, _run_debounced_scan, args=[library_id])
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
        logger.debug(
            "FS event library=%s type=%s path=%s",
            self.library_id,
            getattr(event, "event_type", "?"),
            getattr(event, "src_path", ""),
        )
        schedule_library_scan(self.library_id)


def start_watcher() -> None:
    global _observer
    with _lock:
        if _observer is not None:
            return
        _observer = Observer()
        _observer.daemon = True
        _observer.start()
    reload_watches()
    logger.info("Filesystem watcher started")


def stop_watcher() -> None:
    global _observer
    with _lock:
        for t in _timers.values():
            t.cancel()
        _timers.clear()
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
    """Re-sync observers with enabled libraries that have auto_scan_enabled."""
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
        _observer = Observer()
        _observer.daemon = True
        _observer.start()
        _watched_ids.clear()
        for t in _timers.values():
            t.cancel()
        _timers.clear()

        db = SessionLocal()
        try:
            libs = (
                db.query(Library)
                .filter(Library.enabled.is_(True), Library.auto_scan_enabled.is_(True))
                .all()
            )
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
            "watched_library_ids": sorted(_watched_ids),
            "pending_scans": sorted(_timers.keys()),
            "scanning": sorted(_scanning),
            "debounce_sec": _DEBOUNCE_SEC,
        }
