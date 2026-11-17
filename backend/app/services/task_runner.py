from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path

from sqlalchemy import or_
from sqlalchemy.engine import make_url

from app.config import get_settings
from app.db import SessionLocal
from app.models import BackgroundJob, BackgroundJobItem, Library, MediaItem, FileObservation, utcnow
from app.services import task_store as store
from app.services import task_control
from app.services.ts_files import TsGuard
from app.services.actors import delete_orphan_actors
from app.services.jobs import ScanJob
from app.services.library_revision import bump_revision
from app.services.scanner import _ingest_file, _is_media_file, resolve_library_path
from app.services.scrape import scrape_media_item
from app.services.file_readiness import check_file, FileDeferred, iter_files, ignored_reason
from app.services.naming import SOURCE_NAME_VERSION

logger = logging.getLogger(__name__)


class TaskStopped(Exception):
    def __init__(self, cancelled: bool):
        self.cancelled = cancelled


def _check_stop(factory, job_id: str, stop: threading.Event | None) -> None:
    if task_control.requested(job_id):
        raise TaskStopped(True)
    with factory() as db:
        job = db.get(BackgroundJob, job_id)
        if job is None or job.cancel_requested:
            raise TaskStopped(True)
    if stop is not None and stop.is_set():
        raise TaskStopped(False)


class StopCheck:
    def __init__(self, factory, job_id, stop):
        self.factory, self.job_id, self.stop = factory, job_id, stop
        self.last_poll = float('-inf')

    def __call__(self, *, force=False):
        if task_control.local_requested(self.job_id):
            raise TaskStopped(True)
        if self.stop is not None and self.stop.is_set():
            raise TaskStopped(False)
        now = time.monotonic()
        if force or now - self.last_poll >= 0.2:
            _check_stop(self.factory, self.job_id, self.stop)
            self.last_poll = now


async def _scrape_interruptible(factory, job_id, stop, coroutine):
    work = asyncio.create_task(coroutine)
    try:
        while not work.done():
            _check_stop(factory, job_id, stop)
            await asyncio.wait({work}, timeout=0.2)
        return work.result()
    finally:
        if not work.done():
            work.cancel()
            try:
                await work
            except asyncio.CancelledError:
                pass


def _safe_error(exc: Exception) -> str:
    value = str(exc)[:1000]
    settings = get_settings()
    for key in ("metatube_token", "stash_api_key", "stashscrapers_token", "translate_ai_api_key", "translate_deepl_api_key"):
        secret = getattr(settings, key, "")
        if secret:
            value = value.replace(secret, "[redacted]")
    return value[:400] or type(exc).__name__


def _manifest(factory, job_id: str, stop: threading.Event | None) -> None:
    with factory() as db:
        check_stop = StopCheck(factory, job_id, stop)
        last_commit = time.monotonic()
        def checkpoint():
            nonlocal last_commit
            check_stop()
            if time.monotonic() - last_commit >= 0.25:
                db.commit()
                last_commit = time.monotonic()
                check_stop(force=True)
        guard = TsGuard(checkpoint)
        job = db.get(BackgroundJob, job_id)
        if job.manifest_ready:
            return
        lib = db.get(Library, job.library_id)
        if lib is None:
            raise ValueError("媒体库已不存在")
        # Incomplete discovery has no executed items; safely rebuild it after resume.
        db.query(BackgroundJobItem).filter_by(job_id=job_id).delete()
        job.total, job.scanned, job.waiting = 0, 0, 0
        job.phase, job.message = "discovering", "正在建立任务清单"
        db.commit()
        if job.kind == "scan":
            root = resolve_library_path(lib)
            if not root.is_dir():
                raise ValueError(f"媒体库目录不可访问：{root}")
            raw_paths = json.loads(job.params_json)["inputs"].get("paths")
            settings = get_settings().model_copy(update=json.loads(job.params_json)["settings"])
            deferred_dirs, deferred_paths = set(), set()
            def deferred(path, reason):
                if path.parent in deferred_dirs:
                    return
                deferred_dirs.add(path.parent)
                row = db.query(FileObservation).filter_by(library_id=lib.id, path=str(path)).one_or_none()
                if row is None:
                    row = db.query(FileObservation).filter(FileObservation.library_id == lib.id,
                        FileObservation.reason.like('同目录%TS 疑似分片%'),
                        FileObservation.path.startswith(str(path.parent) + os.sep, autoescape=True)).first()
                    if row and Path(row.path).parent != path.parent:
                        row = None
                if row is None:
                    row = FileObservation(library_id=lib.id, path=str(path))
                    db.add(row)
                row.state, row.reason, row.next_check_at = 'waiting', reason, None
                deferred_paths.add(row.path)
                job.waiting += 1
            paths = None
            if raw_paths is not None:
                paths, parents = [], {}
                for raw in raw_paths:
                    checkpoint()
                    target = Path(os.path.abspath(raw))
                    if ignored_reason(target, root, lib):
                        continue
                    if target.suffix.casefold() == '.ts':
                        if target.parent not in parents:
                            parents[target.parent] = target.parent.resolve()
                        target = parents[target.parent] / target.name
                        if not target.is_relative_to(root):
                            continue
                        if verdict := guard.classify(target, lib):
                            if verdict[0] == 'waiting':
                                deferred(target, verdict[1])
                            continue
                    paths.append(str(target))
                # Filtering all event paths must never turn an empty batch into
                # an unintended full-library scan.
                if not paths:
                    job.scan_manifest_json = json.dumps({'missing': [], 'root_dev': root.stat().st_dev, 'waiting': job.waiting})
                    job.manifest_ready = True
                    db.commit()
                    return
            for scope in paths or []:
                checkpoint()
                target = Path(scope)
                if not target.exists():
                    check_file(db, lib, target)
            scopes = set()
            for scope in paths or []:
                checkpoint()
                scopes.add(Path(scope).resolve())
            query = db.query(MediaItem.id, MediaItem.path, MediaItem.filename, MediaItem.file_size,
                MediaItem.file_mtime_ns, MediaItem.recognition_version, MediaItem.number, MediaItem.scraped_at).filter(MediaItem.library_id == lib.id)
            # Common file events fetch only their own index rows. Large bursts use
            # one query and bounded ancestor checks instead of huge SQLite OR trees.
            if scopes and root not in scopes and len(scopes) <= 100:
                query = query.filter(or_(*(condition for scope in scopes for condition in (
                    MediaItem.path == str(scope),
                    MediaItem.path.startswith(str(scope) + os.sep, autoescape=True),
                ))))
            def in_scope(path):
                return not scopes or path in scopes or any(parent in scopes for parent in path.parents)
            known = {}
            for media in query.yield_per(128):
                check_stop()
                if in_scope(Path(media.path)):
                    known[media.path] = media
            seen = set()
            for idx, path in enumerate(iter_files(root, paths, lib, checkpoint=checkpoint, guard=guard, on_deferred=deferred)):
                if idx % 128 == 0:
                    db.commit()
                    _check_stop(factory, job_id, stop)
                absolute = str(path.resolve())
                seen.add(absolute)
                if ignored_reason(path, root, lib) or path.suffix.lower().lstrip(".") not in settings.extension_set:
                    continue
                job.scanned += 1
                check = check_file(db, lib, path, guard=guard)
                if check.state != "ready":
                    job.waiting += check.state in {"waiting", "unreadable"}
                    continue
                media = known.get(absolute)
                same = media and media.file_size == check.stat.st_size and media.file_mtime_ns == str(check.stat.st_mtime_ns) and media.recognition_version == SOURCE_NAME_VERSION
                if not same:
                    store.add_item(db, job, "index", "index:" + absolute, path.name, path=absolute)
                elif settings.auto_scrape and not media.scraped_at:
                    store.add_item(db, job, "scrape", f"scrape:{media.id}", media.filename, media_id=media.id)
            missing = []
            for absolute, media in known.items():
                checkpoint()
                path = Path(absolute)
                if ignored_reason(path, root, lib) or guard.classify(path, lib):
                    continue
                if absolute not in seen or path.suffix.lower().lstrip(".") not in settings.extension_set:
                    missing.append({"id": media.id, "path": absolute})
            job.scan_manifest_json = json.dumps({"missing": missing, "root_dev": root.stat().st_dev, "waiting": job.waiting})
            # Retire group warnings after files disappear or the user confirms
            # complete recordings, instead of leaving a permanent waiting row.
            for row in db.query(FileObservation).filter(FileObservation.library_id == lib.id,
                    FileObservation.state == 'waiting', FileObservation.next_check_at.is_(None),
                    FileObservation.reason.like('同目录%TS 疑似分片%')):
                checkpoint()
                if row.path in deferred_paths or not in_scope(Path(row.path)):
                    continue
                excluded = ignored_reason(Path(row.path), root, lib)
                if excluded or Path(row.path).parent in deferred_dirs:
                    row.state, row.reason, row.next_check_at = 'ignored', excluded or '同目录已有待确认记录', None
                    continue
                verdict = guard.classify(Path(row.path), lib)
                if verdict and verdict[0] == 'waiting':
                    continue
                check = check_file(db, lib, Path(row.path), guard=guard)
                if check.state in {'ignored', 'unsupported'}:
                    row.state, row.reason, row.next_check_at = check.state, check.reason, None
        elif job.kind == "rescrape_pending":
            rows = db.query(MediaItem.id, MediaItem.filename).filter(
                MediaItem.library_id == lib.id, MediaItem.scraped_at.is_(None),
            ).order_by(MediaItem.id).all()
            for idx, (media_id, filename) in enumerate(rows):
                checkpoint()
                if idx % 128 == 0:
                    db.commit()
                    _check_stop(factory, job_id, stop)
                store.add_item(db, job, "scrape", f"scrape:{media_id}", filename, media_id=media_id)
        else:
            media = db.get(MediaItem, job.media_id)
            if media is None or media.library_id != lib.id:
                raise ValueError("影片已不存在")
            store.add_item(db, job, "scrape", f"scrape:{media.id}", media.filename, media_id=media.id)
        job.manifest_ready = True
        db.commit()


def _followup(db, job: BackgroundJob, checkpoint=None) -> None:
    if job.kind != "scan" or job.followup_ready:
        return
    index_pending = db.query(BackgroundJobItem.id).filter(
        BackgroundJobItem.job_id == job.job_id, BackgroundJobItem.phase == "index",
        BackgroundJobItem.status.in_(("pending", "running")),
    ).first()
    if index_pending:
        return
    params = json.loads(job.params_json)
    keys = set()
    for key, in db.query(BackgroundJobItem.item_key).filter_by(job_id=job.job_id).yield_per(128):
        if checkpoint:
            checkpoint()
        keys.add(key)
    if not params.get("retry_only") and 'prune' not in keys:
        store.add_item(db, job, "prune", "prune", "核对已移除的文件")
    if params["settings"]["auto_scrape"]:
        query = db.query(MediaItem).filter(MediaItem.library_id == job.library_id,
            MediaItem.scraped_at.is_(None))
        successful_ids = db.query(BackgroundJobItem.media_id).filter_by(
            job_id=job.job_id, phase="index", status="succeeded")
        query = query.filter(MediaItem.id.in_(successful_ids))
        for index, media in enumerate(query.with_entities(MediaItem.id, MediaItem.filename).order_by(MediaItem.id).yield_per(128)):
            if checkpoint:
                checkpoint()
            key = f"scrape:{media.id}"
            if key not in keys:
                store.add_item(db, job, "scrape", key, media.filename, media_id=media.id)
                keys.add(key)
            if index % 128 == 127:
                db.commit()
    job.followup_ready = True
    db.commit()


def _prune(db, job, item, factory, stop) -> None:
    check_stop = StopCheck(factory, job.job_id, stop)
    guard = TsGuard(check_stop)
    lib = db.get(Library, job.library_id)
    if lib is None or not resolve_library_path(lib).is_dir():
        raise ValueError("媒体库目录不可访问，已保留索引")
    failed_index = db.query(BackgroundJobItem.id).filter_by(job_id=job.job_id, phase="index", status="failed").first()
    if failed_index:
        store.finish_item(db, job, item, "skipped", error="索引存在失败条目，已跳过清理以保留媒体记录")
        return
    manifest = json.loads(job.scan_manifest_json or "{}")
    if manifest.get("root_dev") is not None and resolve_library_path(lib).stat().st_dev != manifest["root_dev"]:
        raise ValueError("媒体库挂载设备已改变，保留索引")
    removed = 0
    for idx, entry in enumerate(manifest.get("missing", [])):
        check_stop()
        media = db.get(MediaItem, entry["id"])
        if media is None or media.library_id != lib.id or media.path != entry["path"]:
            continue
        media_path = Path(media.path)
        if ignored_reason(media_path, resolve_library_path(lib), lib) or guard.classify(media_path, lib):
            continue
        try:
            missing = not media_path.exists()
        except OSError:
            continue
        if missing or media_path.suffix.lower().lstrip(".") not in get_settings().extension_set:
            db.delete(media)
            removed += 1
    if removed:
        db.flush()
        delete_orphan_actors(db)
    store.finish_item(db, job, item, "succeeded", {"removed": removed})
    if removed:
        bump_revision(job.library_id)


def _step(factory, job_id: str, item_id: int, stop) -> None:
    with factory() as db:
        job, item = db.get(BackgroundJob, job_id), db.get(BackgroundJobItem, item_id)
        if job.cancel_requested:
            raise TaskStopped(True)
        item.status, item.started_at = "running", utcnow()
        job.phase, job.current, job.updated_at = item.phase, item.label, utcnow()
        job.message = {"index": "正在扫描文件", "scrape": "正在刮削元数据", "prune": "正在核对文件"}[item.phase]
        db.commit()
        try:
            lib = db.get(Library, job.library_id)
            if lib is None:
                raise ValueError("媒体库已不存在")
            if item.phase == "index":
                if not Path(item.path).is_file():
                    store.finish_item(db, job, item, "skipped", error="文件已移除")
                    return
                counts = ScanJob(job_id=job_id)
                media = _ingest_file(db, lib, Path(item.path), counts, auto_scrape=False)
                item.media_id = media.id
                stats = {"created": counts.created}
                if json.loads(job.params_json).get("retry_only"):
                    stats["scanned"] = 1
                store.finish_item(db, job, item, "succeeded", stats)
                bump_revision(lib.id)
            elif item.phase == "prune":
                _prune(db, job, item, factory, stop)
            else:
                media = db.get(MediaItem, item.media_id)
                if media is None or media.library_id != lib.id:
                    store.finish_item(db, job, item, "skipped", error="影片已移除")
                    return
                params = json.loads(job.params_json)
                forced = job.kind == "rescrape"
                readiness = check_file(db, lib, Path(media.path), guard=TsGuard(StopCheck(factory, job_id, stop)))
                if readiness.state != "ready":
                    store.finish_item(db, job, item, "skipped", {"waiting": int(readiness.state in {"waiting", "unreadable"})}, error=readiness.reason)
                    return
                if not forced and media.scraped_at:
                    store.finish_item(db, job, item, "skipped", error="影片已完成刮削")
                    return
                inputs = params["inputs"] if forced else {}
                # Old queued overrides and locks no longer replace the source filename.
                db.commit()
                settings = get_settings().model_copy(update=params["settings"])
                ok = asyncio.run(_scrape_interruptible(factory, job_id, stop, scrape_media_item(db, media, force=forced,
                    provider_override=inputs.get("provider"),
                    url_override=inputs.get("url"), settings_override=settings)))
                # scrape_media_item may commit/rollback its own session; refresh job state.
                db.refresh(job)
                db.refresh(item)
                if ok:
                    store.finish_item(db, job, item, "succeeded", {"scraped": 1})
                    bump_revision(lib.id)
                else:
                    store.finish_item(db, job, item, "failed", error="未找到匹配元数据或刮削源执行失败，请检查来源配置与后端日志")
        except FileDeferred as exc:
            store.finish_item(db, job, item, "skipped", {"waiting": int(exc.check.state in {"waiting", "unreadable"})}, error=str(exc))
        except TaskStopped:
            db.rollback()
            raise
        except Exception as exc:
            db.rollback()
            logger.exception("Task item failed job=%s item=%s", job_id, item_id)
            job, item = db.get(BackgroundJob, job_id), db.get(BackgroundJobItem, item_id)
            if item.status not in {"pending", "running"}:
                raise
            store.finish_item(db, job, item, "failed", error=_safe_error(exc))


def _index_batch(factory, job_id: str, stop) -> None:
    """Bounded index-only transaction; network scraping keeps per-item checkpoints."""
    with factory() as db:
        check_stop = StopCheck(factory, job_id, stop)
        guard = TsGuard(check_stop)
        interruption = None
        job = db.get(BackgroundJob, job_id)
        lib = db.get(Library, job.library_id)
        if lib is None:
            raise ValueError("媒体库已不存在")
        rows = db.query(BackgroundJobItem).filter_by(job_id=job_id, phase="index", status="pending").order_by(BackgroundJobItem.id).limit(32).all()
        for item in rows:
            item.status, item.started_at = "running", utcnow()
        job.phase, job.message = "index", "正在增量索引文件"
        db.commit()
        started = time.monotonic()
        for item in rows:
            stats, error, outcome = {}, None, "succeeded"
            try:
                check_stop()
                with db.begin_nested():
                    check = check_file(db, lib, Path(item.path), guard=guard)
                    check_stop()
                    if check.state != "ready":
                        outcome, error = "skipped", check.reason
                        stats = {"waiting": int(check.state in {"waiting", "unreadable"})}
                    else:
                        counts = ScanJob(job_id=job_id)
                        media = _ingest_file(db, lib, Path(item.path), counts, auto_scrape=False, check=check)
                        item.media_id = media.id
                        stats = {"created": counts.created}
                        if json.loads(job.params_json).get("retry_only"):
                            stats["scanned"] = 1
            except TaskStopped as exc:
                interruption = exc
                break
            except Exception as exc:
                outcome, error = "failed", _safe_error(exc)
                logger.exception("Index failed job=%s path=%s", job_id, item.path)
            store.finish_item(db, job, item, outcome, stats, error=error, commit=False)
            job.current = item.label
            if time.monotonic() - started >= 0.25:
                break
        for item in rows:
            if item.status == "running":
                item.status = "pending"
        db.commit()
        bump_revision(lib.id)
        if interruption:
            raise interruption


def _parallel_steps(factory, job_id, item_ids, stop, pool):
    futures = {pool.submit(_step, factory, job_id, item_id, stop) for item_id in item_ids}
    pending = set(futures)
    try:
        while pending:
            _check_stop(factory, job_id, stop)
            done, pending = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
            for future in done:
                future.result()
    finally:
        # Never finalize a cancelled job while its running items can still commit.
        for future in pending:
            future.cancel()
        wait([future for future in futures if not future.cancelled()])


def execute_job(job_id: str, factory=None, stop: threading.Event | None = None,
                *, step_pool=None, concurrency: int = 1) -> None:
    factory = factory or SessionLocal
    with factory() as db:
        claimed = db.query(BackgroundJob).filter_by(job_id=job_id, status="pending").update(
            {"status": "running", "updated_at": utcnow()}, synchronize_session=False)
        db.commit()
        if not claimed:
            return
    task_control.register(job_id)
    try:
        _check_stop(factory, job_id, stop)
        _manifest(factory, job_id, stop)
        while True:
            _check_stop(factory, job_id, stop)
            with factory() as db:
                job = db.get(BackgroundJob, job_id)
                _followup(db, job, StopCheck(factory, job_id, stop))
                next_id = db.query(BackgroundJobItem.id).filter_by(job_id=job_id, status="pending").order_by(BackgroundJobItem.id).first()
                if next_id is None:
                    db.refresh(job)
                    if job.cancel_requested:
                        raise TaskStopped(True)
                    job.status = "error" if job.failed and not job.succeeded else "done"
                    job.active_key, job.current, job.finished_at = None, None, utcnow()
                    job.message = f"处理完成：成功 {job.succeeded}，失败 {job.failed}，跳过 {job.skipped}，等待就绪 {job.waiting}"
                    db.commit()
                    return
                item_id = next_id[0]
                phase = db.get(BackgroundJobItem, item_id).phase
                parallel_ids = [row[0] for row in db.query(BackgroundJobItem.id).filter_by(
                    job_id=job_id, status='pending', phase='scrape').order_by(BackgroundJobItem.id).limit(concurrency)] if phase == 'scrape' and step_pool else []
            if parallel_ids:
                _parallel_steps(factory, job_id, parallel_ids, stop, step_pool)
            elif phase == "index":
                _index_batch(factory, job_id, stop)
            else:
                _step(factory, job_id, item_id, stop)
    except TaskStopped as exc:
        with factory() as db:
            job = db.get(BackgroundJob, job_id)
            job.status = "cancelled" if exc.cancelled else "interrupted"
            if exc.cancelled:
                job.cancel_requested = True
            job.active_key, job.current, job.finished_at = None, None, utcnow()
            job.message = "已取消，可继续未完成条目" if exc.cancelled else "服务已停止，可继续未完成条目"
            db.query(BackgroundJobItem).filter_by(job_id=job_id, status="running").update({"status": "pending"})
            db.commit()
    except Exception as exc:
        logger.exception("Task failed job=%s", job_id)
        with factory() as db:
            job = db.get(BackgroundJob, job_id)
            job.status, job.active_key, job.current, job.finished_at = "error", None, None, utcnow()
            db.query(BackgroundJobItem).filter_by(job_id=job_id, status="running").update({"status": "pending"})
            job.message = "执行失败：" + _safe_error(exc)
            db.commit()
    finally:
        task_control.unregister(job_id)
        task_control.clear(job_id)


def recover_interrupted(factory=None) -> None:
    """Called only while holding the exclusive worker lock."""
    factory = factory or SessionLocal
    with factory() as db:
        for job in db.query(BackgroundJob).filter(BackgroundJob.status.in_(("running", "cancelling"))).all():
            if task_control.requested(job.job_id):
                job.cancel_requested = True
            for item in db.query(BackgroundJobItem).filter_by(job_id=job.job_id, status="running"):
                media = db.get(MediaItem, item.media_id) if item.media_id else None
                # Metadata may have committed immediately before the process stopped.
                if item.phase == "scrape" and media and media.scraped_at and item.started_at and media.scraped_at.replace(tzinfo=None) >= item.started_at.replace(tzinfo=None):
                    item.status, item.result_json = "succeeded", '{"scraped":1}'
                else:
                    item.status = "pending"
            db.flush()
            store.recount(db, job)
            job.status = "cancelled" if job.cancel_requested else "interrupted"
            job.active_key, job.current, job.finished_at = None, None, utcnow()
            job.message = "服务重启时任务中断，可继续未完成条目"
        db.commit()


class TaskRunner:
    def __init__(self):
        self.stop_event = threading.Event()
        self.is_owner = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._loop, name="persistent-task-worker", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        store.wakeup.set()
        if self.thread:
            self.thread.join(timeout=5)

    def _lock(self):
        database = make_url(get_settings().resolved_database_url).database
        path = Path(str(Path(database).resolve()) + ".tasks.lock")
        handle = path.open("a+b")
        try:
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return handle
        except OSError:
            handle.close()
            return None

    def _loop(self) -> None:
        lock = None
        job_pool = step_pool = None
        active = {}
        concurrency = 0
        try:
            while not self.stop_event.is_set() and lock is None:
                lock = self._lock()
                if lock is None:
                    self.stop_event.wait(1)
            if lock is None:
                return
            self.is_owner.set()
            recover_interrupted()
            while not self.stop_event.is_set():
                try:
                    store.wakeup.clear()
                    for future in list(active):
                        if future.done():
                            active.pop(future)
                            future.result()
                    desired = max(1, min(8, get_settings().task_concurrency))
                    if desired != concurrency and not active:
                        if job_pool:
                            job_pool.shutdown(wait=True)
                            step_pool.shutdown(wait=True)
                        concurrency = desired
                        job_pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix='metadata-job')
                        step_pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix='metadata-item')
                    with SessionLocal() as db:
                        rows = db.query(BackgroundJob.job_id, BackgroundJob.library_id, BackgroundJob.kind).filter_by(status="pending").order_by(BackgroundJob.created_at, BackgroundJob.job_id).all()
                    if desired == concurrency:
                        for row in rows:
                            if len(active) >= concurrency or self.stop_event.is_set():
                                break
                            if any(current.job_id == row.job_id or current.library_id == row.library_id and
                                   (current.kind != 'rescrape' or row.kind != 'rescrape') for current in active.values()):
                                continue
                            future = job_pool.submit(execute_job, row.job_id, stop=self.stop_event,
                                step_pool=step_pool, concurrency=concurrency)
                            active[future] = row
                            future.add_done_callback(lambda _: store.wakeup.set())
                    store.wakeup.wait(0.2 if active else 30)
                except Exception:
                    logger.exception("Task worker will retry after a database error")
                    self.stop_event.wait(1)
        except Exception:
            logger.exception("Persistent task worker stopped unexpectedly")
        finally:
            self.stop_event.set()
            if job_pool:
                job_pool.shutdown(wait=True, cancel_futures=True)
            if step_pool:
                step_pool.shutdown(wait=True, cancel_futures=True)
            self.is_owner.clear()
            if lock is not None:
                lock.close()


runner = TaskRunner()
