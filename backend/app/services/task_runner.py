from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from pathlib import Path

from sqlalchemy.engine import make_url

from app.config import get_settings
from app.db import SessionLocal
from app.models import BackgroundJob, BackgroundJobItem, Library, MediaItem, utcnow
from app.services import task_store as store
from app.services.actors import delete_orphan_actors
from app.services.jobs import ScanJob
from app.services.library_revision import bump_revision
from app.services.naming import normalize_number
from app.services.scanner import _ingest_file, _is_media_file, resolve_library_path
from app.services.scrape import scrape_media_item

logger = logging.getLogger(__name__)


class TaskStopped(Exception):
    def __init__(self, cancelled: bool):
        self.cancelled = cancelled


def _check_stop(factory, job_id: str, stop: threading.Event | None) -> None:
    with factory() as db:
        job = db.get(BackgroundJob, job_id)
        if job is None or job.cancel_requested:
            raise TaskStopped(True)
    if stop is not None and stop.is_set():
        raise TaskStopped(False)


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
        job = db.get(BackgroundJob, job_id)
        if job.manifest_ready:
            return
        lib = db.get(Library, job.library_id)
        if lib is None:
            raise ValueError("媒体库已不存在")
        # Incomplete discovery has no executed items; safely rebuild it after resume.
        db.query(BackgroundJobItem).filter_by(job_id=job_id).delete()
        job.total = 0
        job.phase, job.message = "discovering", "正在建立任务清单"
        db.commit()
        if job.kind == "scan":
            root = resolve_library_path(lib)
            if not root.is_dir():
                raise ValueError(f"媒体库目录不可访问：{root}")
            paths = json.loads(job.params_json)["inputs"].get("paths")
            settings = get_settings().model_copy(update=json.loads(job.params_json)["settings"])
            if paths:
                def candidates():
                    for raw in paths:
                        target = Path(raw).resolve()
                        if target.is_relative_to(root):
                            yield from target.rglob("*") if target.is_dir() else [target]
                targets = candidates()
            else:
                targets = root.rglob("*")
            seen = set()
            for idx, path in enumerate(targets):
                if idx % 32 == 0:
                    db.commit()
                    _check_stop(factory, job_id, stop)
                if _is_media_file(path, settings.extension_set):
                    absolute = str(path.resolve())
                    if Path(absolute).is_relative_to(root) and absolute not in seen:
                        store.add_item(db, job, "index", "index:" + absolute, path.name, path=absolute)
                        seen.add(absolute)
        elif job.kind == "rescrape_pending":
            rows = db.query(MediaItem.id, MediaItem.filename).filter(
                MediaItem.library_id == lib.id, MediaItem.number.isnot(None), MediaItem.scraped_at.is_(None),
            ).order_by(MediaItem.id).all()
            for idx, (media_id, filename) in enumerate(rows):
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


def _followup(db, job: BackgroundJob) -> None:
    if job.kind != "scan" or job.followup_ready:
        return
    index_pending = db.query(BackgroundJobItem.id).filter(
        BackgroundJobItem.job_id == job.job_id, BackgroundJobItem.phase == "index",
        BackgroundJobItem.status.in_(("pending", "running")),
    ).first()
    if index_pending:
        return
    params = json.loads(job.params_json)
    if not params.get("retry_only"):
        store.add_item(db, job, "prune", "prune", "核对已移除的文件")
    if params["settings"]["auto_scrape"]:
        query = db.query(MediaItem).filter(MediaItem.library_id == job.library_id,
            MediaItem.number.isnot(None), MediaItem.scraped_at.is_(None))
        successful_ids = db.query(BackgroundJobItem.media_id).filter_by(
            job_id=job.job_id, phase="index", status="succeeded")
        query = query.filter(MediaItem.id.in_(successful_ids))
        keys = {key for key, in db.query(BackgroundJobItem.item_key).filter_by(job_id=job.job_id)}
        for media in query.order_by(MediaItem.id):
            key = f"scrape:{media.id}"
            if key not in keys:
                store.add_item(db, job, "scrape", key, media.filename, media_id=media.id)
    job.followup_ready = True
    db.commit()


def _prune(db, job, item, factory, stop) -> None:
    lib = db.get(Library, job.library_id)
    if lib is None or not resolve_library_path(lib).is_dir():
        raise ValueError("媒体库目录不可访问，已保留索引")
    failed_index = db.query(BackgroundJobItem.id).filter_by(job_id=job.job_id, phase="index", status="failed").first()
    if failed_index:
        store.finish_item(db, job, item, "skipped", error="索引存在失败条目，已跳过清理以保留媒体记录")
        return
    removed = 0
    scopes = json.loads(job.params_json)["inputs"].get("paths")
    seen = {path for path, in db.query(BackgroundJobItem.path).filter_by(job_id=job.job_id, phase="index")} if not scopes else set()
    for idx, media in enumerate(db.query(MediaItem).filter_by(library_id=job.library_id).all()):
        if idx % 64 == 0:
            _check_stop(factory, job.job_id, stop)
        media_path = Path(media.path)
        if scopes and not any(media_path.is_relative_to(Path(scope).resolve()) for scope in scopes):
            continue
        if not media_path.exists() or not scopes and str(media_path) not in seen:
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
                store.finish_item(db, job, item, "succeeded", {"scanned": 1, "created": counts.created})
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
                if not forced and media.scraped_at:
                    store.finish_item(db, job, item, "skipped", error="影片已完成刮削")
                    return
                inputs = params["inputs"] if forced else {}
                if inputs.get("number"):
                    media.number = normalize_number(inputs["number"])
                    db.commit()
                settings = get_settings().model_copy(update=params["settings"])
                ok = asyncio.run(scrape_media_item(db, media, force=forced,
                    provider_override=inputs.get("provider"), fallback_override=inputs.get("fallback"),
                    url_override=inputs.get("url"), settings_override=settings))
                # scrape_media_item may commit/rollback its own session; refresh job state.
                db.refresh(job)
                db.refresh(item)
                if ok:
                    store.finish_item(db, job, item, "succeeded", {"scraped": 1})
                    bump_revision(lib.id)
                else:
                    store.finish_item(db, job, item, "failed", error="未找到匹配元数据或刮削源执行失败，请检查来源配置与后端日志")
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


def execute_job(job_id: str, factory=None, stop: threading.Event | None = None) -> None:
    factory = factory or SessionLocal
    with factory() as db:
        claimed = db.query(BackgroundJob).filter_by(job_id=job_id, status="pending").update(
            {"status": "running", "updated_at": utcnow()}, synchronize_session=False)
        db.commit()
        if not claimed:
            return
    try:
        _check_stop(factory, job_id, stop)
        _manifest(factory, job_id, stop)
        while True:
            _check_stop(factory, job_id, stop)
            with factory() as db:
                job = db.get(BackgroundJob, job_id)
                _followup(db, job)
                next_id = db.query(BackgroundJobItem.id).filter_by(job_id=job_id, status="pending").order_by(BackgroundJobItem.id).first()
                if next_id is None:
                    db.refresh(job)
                    if job.cancel_requested:
                        raise TaskStopped(True)
                    job.status = "error" if job.failed and not job.succeeded else "done"
                    job.active_key, job.current, job.finished_at = None, None, utcnow()
                    job.message = f"处理完成：成功 {job.succeeded}，失败 {job.failed}，跳过 {job.skipped}"
                    db.commit()
                    return
                item_id = next_id[0]
            _step(factory, job_id, item_id, stop)
    except TaskStopped as exc:
        with factory() as db:
            job = db.get(BackgroundJob, job_id)
            job.status = "cancelled" if exc.cancelled else "interrupted"
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


def recover_interrupted(factory=None) -> None:
    """Called only while holding the exclusive worker lock."""
    factory = factory or SessionLocal
    with factory() as db:
        for job in db.query(BackgroundJob).filter(BackgroundJob.status.in_(("running", "cancelling"))).all():
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
        try:
            while not self.stop_event.is_set() and lock is None:
                lock = self._lock()
                if lock is None:
                    self.stop_event.wait(1)
            if lock is None:
                return
            recover_interrupted()
            while not self.stop_event.is_set():
                try:
                    store.wakeup.clear()
                    with SessionLocal() as db:
                        row = db.query(BackgroundJob.job_id).filter_by(status="pending").order_by(BackgroundJob.created_at, BackgroundJob.job_id).first()
                    if row:
                        execute_job(row[0], stop=self.stop_event)
                    else:
                        store.wakeup.wait(1)
                except Exception:
                    logger.exception("Task worker will retry after a database error")
                    self.stop_event.wait(1)
        except Exception:
            logger.exception("Persistent task worker stopped unexpectedly")
        finally:
            if lock is not None:
                lock.close()


runner = TaskRunner()
