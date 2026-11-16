from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from app.config import get_settings
from app.db import SessionLocal
from app.models import Library, FileObservation, utcnow
from app.services.file_readiness import ignored_reason, ignored_dirs, iter_files, root_path, control_target
from app.services.task_store import enqueue, active_for_library, TaskConflict

logger = logging.getLogger(__name__)


def coalesce_paths(paths: set[str]) -> list[str]:
    kept: set[Path] = set()
    for path in sorted((Path(raw) for raw in paths), key=lambda p: (len(p.parts), str(p))):
        if not any(parent in kept for parent in path.parents):
            kept.add(path)
    return sorted(str(path) for path in kept)


def media_event_path(path: str) -> bool:
    target = Path(path)
    if control_target(target):
        return True
    return target.suffix.lower().lstrip(".") in get_settings().extension_set and not ignored_reason(target, target.parent)


class Handler(FileSystemEventHandler):
    def __init__(self, manager, library_id):
        self.manager, self.library_id = manager, library_id

    def on_any_event(self, event):
        if event.event_type in {"opened", "closed_no_write"} or event.is_directory and event.event_type == "modified":
            return
        paths = []
        for raw in (getattr(event, "src_path", None), getattr(event, "dest_path", None)):
            if raw and (event.is_directory or media_event_path(str(raw))):
                path = Path(str(raw))
                paths.append(str(control_target(path) or path))
        if paths:
            self.manager.schedule(self.library_id, paths)


@dataclass
class WatchState:
    library: Library
    fingerprint: tuple
    observer: object | None = None
    actual_mode: str = "poll"
    snapshot: dict[str, tuple[int, int]] | None = None
    next_poll: float = 0
    idle_rounds: int = 0
    last_error: str | None = None


class AutoScanner:
    def __init__(self, factory=SessionLocal):
        self.factory = factory
        self.states: dict[int, WatchState] = {}
        self.pending: dict[int, set[str]] = {}
        self.deadlines: dict[int, float] = {}
        self.first_events: dict[int, float] = {}
        self.generations: dict[int, int] = {}
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.stop_event = threading.Event()
        self.thread = None
        self.dirty = True
        self.next_config = 0.0
        self.next_readiness = 0.0

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._loop, name="incremental-auto-scanner", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=5)

    def reload(self):
        self.dirty = True
        self.wake.set()

    def schedule(self, library_id, paths, *, immediate=False, now=None):
        now = time.monotonic() if now is None else now
        state = self.states.get(library_id)
        if state:
            root = root_path(state.library)
            paths = [raw for raw in paths if not ignored_reason(Path(raw), root, state.library) and Path(raw).name.casefold() not in ignored_dirs(state.library)]
        if not paths:
            return
        with self.lock:
            self.pending.setdefault(library_id, set()).update(paths)
            self.generations[library_id] = self.generations.get(library_id, 0) + 1
            first = self.first_events.setdefault(library_id, now)
            self.deadlines[library_id] = now if immediate else min(now + get_settings().scan_event_debounce_seconds, first + 60)
        self.wake.set()

    def _refresh(self, now):
        with self.factory() as db:
            libs = db.query(Library).filter_by(enabled=True, auto_scan_enabled=True).all()
            for lib in libs:
                if lib.next_full_scan_at is None:
                    lib.next_full_scan_at = utcnow() + timedelta(seconds=lib.full_scan_interval_seconds)
            db.commit()
            for lib in libs:
                db.refresh(lib)
                db.expunge(lib)
        wanted = {lib.id: lib for lib in libs}
        for library_id in list(self.states):
            if library_id not in wanted:
                self._unwatch(library_id)
        for library_id, lib in wanted.items():
            key = (lib.path, lib.scan_mode, lib.scan_interval_seconds, lib.ignore_dirs,
                   lib.file_settle_seconds, lib.parent_fallback_depth, lib.full_scan_interval_seconds)
            old = self.states.get(library_id)
            if old and old.fingerprint == key:
                old.library = lib
                continue
            if old:
                self._unwatch(library_id, keep_pending=True)
            interval = max(30, lib.scan_interval_seconds or get_settings().scan_poll_interval_seconds)
            state = WatchState(lib, key, next_poll=now + interval)
            if lib.scan_mode == "native":
                observer = Observer()
                try:
                    observer.schedule(Handler(self, library_id), str(root_path(lib)), recursive=True)
                    observer.start()
                    state.observer, state.actual_mode = observer, "native"
                except Exception:
                    observer.stop()
                    if observer.is_alive():
                        observer.join(timeout=2)
                    logger.warning("Native monitoring unavailable; using low-frequency polling for library=%s", library_id)
                    state.last_error = "原生监听不可用，已回退低频轮询"
            self.states[library_id] = state
        self.next_config, self.dirty = now + 60, False

    def _unwatch(self, library_id, keep_pending=False):
        state = self.states.pop(library_id)
        if state.observer:
            state.observer.stop()
            state.observer.join(timeout=2)
        if not keep_pending:
            with self.lock:
                self.pending.pop(library_id, None)
                self.deadlines.pop(library_id, None)
                self.first_events.pop(library_id, None)
                self.generations.pop(library_id, None)

    def snapshot(self, lib):
        root = root_path(lib)
        if not root.is_dir():
            raise OSError("媒体库目录暂时不可访问")
        result = {}
        for path in iter_files(root, None, lib):
            if not media_event_path(str(path)) or ignored_reason(path, root, lib) and not control_target(path):
                continue
            stat = path.stat()
            result[str(path)] = (stat.st_size, stat.st_mtime_ns)
        return result

    def tick(self, now=None):
        now = time.monotonic() if now is None else now
        if self.dirty or now >= self.next_config:
            self._refresh(now)
        for library_id, state in list(self.states.items()):
            lib = state.library
            if state.actual_mode == "poll" and now >= state.next_poll:
                try:
                    snapshot = self.snapshot(lib)
                    previous = state.snapshot or {}
                    changed = {path for path in previous.keys() | snapshot.keys() if previous.get(path) != snapshot.get(path)}
                    if changed:
                        self.schedule(library_id, [str(control_target(Path(path)) or Path(path)) for path in changed], immediate=True, now=now)
                    state.snapshot = snapshot
                    state.idle_rounds = 0 if changed else min(3, state.idle_rounds + 1)
                    state.last_error = None
                except OSError:
                    state.last_error = "目录暂时不可访问，保留索引并稍后重试"
                interval = max(30, lib.scan_interval_seconds or get_settings().scan_poll_interval_seconds)
                state.next_poll = now + min(interval * 2 ** state.idle_rounds, max(interval, 600))
        if now >= self.next_readiness and self.states:
            with self.factory() as db:
                due = db.query(FileObservation).filter(FileObservation.library_id.in_(list(self.states)),
                    FileObservation.state.in_(("waiting", "unreadable")), FileObservation.next_check_at <= utcnow()).all()
                for observation in due:
                    lib = self.states[observation.library_id].library
                    reason = ignored_reason(Path(observation.path), root_path(lib), lib)
                    if reason or Path(observation.path).suffix.lower().lstrip('.') not in get_settings().extension_set:
                        observation.state, observation.next_check_at = "ignored", None
                        observation.reason = reason or "不在扫描扩展名白名单中"
                    else:
                        self.schedule(observation.library_id, [observation.path], immediate=True, now=now)
                db.commit()
                for lib in db.query(Library).filter(Library.id.in_(list(self.states)), Library.next_full_scan_at <= utcnow()):
                    if not active_for_library(db, lib.id):
                        try:
                            enqueue(db, "scan", lib)
                            lib.next_full_scan_at = utcnow() + timedelta(seconds=lib.full_scan_interval_seconds)
                            db.commit()
                        except TaskConflict:
                            pass
            self.next_readiness = now + 30
        with self.lock:
            ready = [(library_id, set(paths), self.generations.get(library_id, 0)) for library_id, paths in self.pending.items() if self.deadlines.get(library_id, now + 1) <= now]
        for library_id, paths, generation in ready:
            with self.factory() as db:
                lib = db.get(Library, library_id)
                if lib is None or not lib.enabled or not lib.auto_scan_enabled:
                    with self.lock:
                        self.pending.pop(library_id, None)
                        self.deadlines.pop(library_id, None)
                        self.first_events.pop(library_id, None)
                        self.generations.pop(library_id, None)
                    continue
                if active_for_library(db, library_id):
                    self.deadlines[library_id] = now + 30
                    continue
                try:
                    enqueue(db, "scan", lib, inputs={"paths": coalesce_paths(paths)})
                    with self.lock:
                        # A repeated event for the same path can arrive while enqueue
                        # wakes the worker; retain it for a second readiness check.
                        if self.generations.get(library_id, 0) != generation:
                            continue
                        remaining = self.pending.get(library_id, set()) - paths
                        if remaining:
                            self.pending[library_id] = remaining
                        else:
                            self.pending.pop(library_id, None)
                            self.deadlines.pop(library_id, None)
                            self.first_events.pop(library_id, None)
                            self.generations.pop(library_id, None)
                except TaskConflict:
                    self.deadlines[library_id] = now + 30

    def _loop(self):
        from app.services.task_runner import runner
        try:
            while not self.stop_event.is_set():
                self.wake.clear()
                if runner.is_owner.is_set():
                    try:
                        self.tick()
                    except Exception:
                        logger.exception("Automatic scan tick failed; retrying later")
                self.wake.wait(5 if self.states or self.dirty else 30)
        finally:
            for library_id in list(self.states):
                self._unwatch(library_id)

    def status(self):
        states = list(self.states.items())
        with self.lock:
            pending = sorted(self.pending)
        return {"running": bool(self.thread and self.thread.is_alive()), "observer_type": "adaptive",
            "poll_interval_sec": get_settings().scan_poll_interval_seconds,
            "watched_library_ids": sorted(key for key, _ in states), "pending_scans": pending,
            "libraries": [{"id": key, "mode": state.actual_mode, "error": state.last_error,
                "idle_rounds": state.idle_rounds} for key, state in states]}


manager = AutoScanner()
