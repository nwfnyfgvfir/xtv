"""Compatibility entry points for the incremental automatic scanner."""
from app.services.auto_scan import manager, media_event_path
from app.services.scan_files import root_path as resolve_library_path


def start_watcher():
    manager.start()


def stop_watcher():
    manager.stop()


def reload_watches():
    manager.reload()


def schedule_library_scan(library_id, paths=None):
    manager.schedule(library_id, paths or [])


def watcher_status():
    return manager.status()


def _is_media_path(path):
    return media_event_path(path)
