"""Fast cancellation signals; SQLite remains the durable task history."""
from __future__ import annotations

import hashlib
import logging
import threading

from app.config import get_settings

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_events: dict[str, threading.Event] = {}


def _marker(job_id):
    name = hashlib.sha256(job_id.encode()).hexdigest()[:32]
    return get_settings().data_dir_path / f'.{name}.tasks.cancel'


def register(job_id):
    with _lock:
        _events[job_id] = threading.Event()


def unregister(job_id):
    with _lock:
        _events.pop(job_id, None)


def request_cancel(job_id):
    # A separate API process can signal a worker even while SQLite has a writer.
    try:
        marker = _marker(job_id)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch(exist_ok=True)
    except OSError:
        logger.warning('Fast cancellation marker unavailable for task=%s', job_id)
    with _lock:
        if event := _events.get(job_id):
            event.set()


def local_requested(job_id):
    with _lock:
        event = _events.get(job_id)
        return bool(event and event.is_set())


def requested(job_id):
    if local_requested(job_id):
        return True
    try:
        return _marker(job_id).exists()
    except OSError:
        return False


def clear(job_id):
    try:
        _marker(job_id).unlink(missing_ok=True)
    except OSError:
        logger.warning('Could not clear cancellation marker for task=%s', job_id)
