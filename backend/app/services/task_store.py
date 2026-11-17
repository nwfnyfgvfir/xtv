from __future__ import annotations

import json
import threading
import uuid
from typing import Any

from sqlalchemy import case
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import BackgroundJob, BackgroundJobItem, Library, MediaItem, utcnow
from app.schemas import TaskOut
from app.services import task_control

ACTIVE = ("pending", "running", "cancelling")
TERMINAL = ("done", "error", "cancelled", "interrupted")
wakeup = threading.Event()


class TaskConflict(Exception):
    def __init__(self, message: str, job_id: str | None = None):
        super().__init__(message)
        self.job_id = job_id


def source_snapshot() -> dict[str, Any]:
    settings = get_settings()
    # Connection credentials stay in settings, never in task rows or responses.
    fields = ["scrape_source", "auto_scrape", "scan_extensions"]
    for prefix, provider, priority in (
        ("metatube", "provider", "provider_priority"),
        ("stash", "scraper", "scraper_priority"),
        ("stashscrapers", "scraper", "scraper_priority"),
    ):
        fields.extend(f"{prefix}_{key}" for key in (provider, priority, "fallback"))
    return {key: getattr(settings, key) for key in fields}


def resource_key(kind: str, library_id: int | None, media_id: int | None) -> str:
    return f"{kind}:{media_id if kind == 'rescrape' else library_id}"


def active_for_library(db: Session, library_id: int) -> bool:
    return db.query(BackgroundJob.job_id).filter(
        BackgroundJob.library_id == library_id, BackgroundJob.status.in_(ACTIVE),
    ).first() is not None


def task_out(db: Session, job: BackgroundJob) -> TaskOut:
    errors = db.query(BackgroundJobItem).filter_by(job_id=job.job_id, status="failed").order_by(BackgroundJobItem.id).limit(10).all()
    fields = {key: getattr(job, key) for key in (
        "job_id", "kind", "status", "library_id", "library_name", "media_id", "media_label", "parent_id",
        "phase", "current", "total", "processed", "succeeded", "failed", "skipped",
        "scanned", "created", "scraped", "removed", "waiting", "message", "cancel_requested",
        "created_at", "updated_at", "finished_at",
    )}
    target_exists = job.library_id is not None and (job.kind != "rescrape" or db.get(MediaItem, job.media_id) is not None)
    return TaskOut(**fields, errors=[f"{item.label}: {item.error}" for item in errors],
        retryable=target_exists and job.status in TERMINAL and job.failed > 0 and db.query(BackgroundJob.job_id).filter_by(parent_id=job.job_id).first() is None,
        resumable=target_exists and (job.status in {"interrupted", "cancelled"} or job.status == "error" and job.failed == 0))


def enqueue(db: Session, kind: str, library: Library, *, media_id: int | None = None,
            inputs: dict[str, Any] | None = None) -> BackgroundJob:
    params = {"settings": source_snapshot(), "inputs": inputs or {}, "library_path": library.path}
    key = resource_key(kind, library.id, media_id)
    existing = db.query(BackgroundJob).filter_by(active_key=key).first()
    if existing:
        if json.loads(existing.params_json) != params:
            raise TaskConflict("已有参数不同的任务正在执行，请先取消或等待完成", existing.job_id)
        return existing
    job = BackgroundJob(job_id=uuid.uuid4().hex, kind=kind, library_id=library.id,
        library_name=library.name, media_id=media_id, active_key=key,
        params_json=json.dumps(params, ensure_ascii=False, sort_keys=True), message="等待执行")
    if media_id:
        media = db.get(MediaItem, media_id)
        job.media_label = media.filename if media else None
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(BackgroundJob).filter_by(active_key=key).one_or_none()
        if existing is None:
            raise
        if json.loads(existing.params_json) != params:
            raise TaskConflict("已有参数不同的任务正在执行，请先取消或等待完成", existing.job_id)
        return existing
    wakeup.set()
    return job


def cancel(db: Session, job: BackgroundJob) -> BackgroundJob:
    if job.status not in ACTIVE:
        return job
    task_control.request_cancel(job.job_id)
    queued = BackgroundJob.status == 'pending'
    # Evaluate the current row atomically: a stale API read must not turn a
    # finished task back into an eternally "cancelling" task.
    db.query(BackgroundJob).filter(BackgroundJob.job_id == job.job_id,
        BackgroundJob.status.in_(ACTIVE)).update({
            'cancel_requested': True,
            'status': case((queued, 'cancelled'), else_='cancelling'),
            'active_key': case((queued, None), else_=BackgroundJob.active_key),
            'finished_at': case((queued, utcnow()), else_=BackgroundJob.finished_at),
            'updated_at': utcnow(),
            'message': case((queued, '已取消，未完成条目可继续'), else_='正在停止任务，已请求中断当前操作'),
        }, synchronize_session=False)
    db.commit()
    db.refresh(job)
    if job.status not in ACTIVE:
        task_control.clear(job.job_id)
    wakeup.set()
    return job


def _require_free(db: Session, job: BackgroundJob) -> str:
    if job.library_id is None or db.get(Library, job.library_id) is None:
        raise TaskConflict("该任务的媒体库已不存在")
    if job.kind == "rescrape" and db.get(MediaItem, job.media_id) is None:
        raise TaskConflict("该任务的影片已不存在")
    if job.kind == "scan" and db.get(Library, job.library_id).path != json.loads(job.params_json).get("library_path"):
        raise TaskConflict("媒体库目录已变更，请新建扫描任务")
    key = resource_key(job.kind, job.library_id, job.media_id)
    existing = db.query(BackgroundJob).filter_by(active_key=key).first()
    if existing:
        raise TaskConflict("该资源已有任务正在执行，请先取消或等待完成", existing.job_id)
    return key


def resume(db: Session, job: BackgroundJob) -> BackgroundJob:
    if job.status in ACTIVE:
        return job
    if not task_out(db, job).resumable:
        raise TaskConflict("该任务无法继续，可重试失败条目")
    job.active_key = _require_free(db, job)
    task_control.clear(job.job_id)
    job.status, job.cancel_requested, job.finished_at = "pending", False, None
    db.query(BackgroundJobItem).filter_by(job_id=job.job_id, status="running").update({"status": "pending"})
    job.message = "等待继续未完成条目"
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise TaskConflict("该资源已有任务正在执行，请先取消或等待完成") from exc
    wakeup.set()
    return job


def retry_failed(db: Session, job: BackgroundJob) -> BackgroundJob:
    if job.status not in TERMINAL or job.failed == 0:
        raise TaskConflict("只有已结束任务的失败条目可以重试")
    existing = db.query(BackgroundJob).filter_by(parent_id=job.job_id).first()
    if existing:
        return existing
    key = _require_free(db, job)
    params = json.loads(job.params_json)
    params["retry_only"] = True
    retry = BackgroundJob(job_id=uuid.uuid4().hex, kind=job.kind, library_id=job.library_id,
        library_name=job.library_name, media_id=job.media_id, media_label=job.media_label, parent_id=job.job_id,
        active_key=key, params_json=json.dumps(params, ensure_ascii=False), manifest_ready=True,
        scan_manifest_json=job.scan_manifest_json,
        message="等待重试失败条目")
    try:
        db.add(retry)
        db.flush()
        failed_items = db.query(BackgroundJobItem).filter_by(job_id=job.job_id, status="failed").all()
        for item in failed_items:
            db.add(BackgroundJobItem(job_id=retry.job_id, item_key=item.item_key, phase=item.phase,
                label=item.label, path=item.path, media_id=item.media_id))
        retry.total = len(failed_items)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.query(BackgroundJob).filter_by(parent_id=job.job_id).first()
        if existing:
            return existing
        raise TaskConflict("该资源已有任务正在执行，请先取消或等待完成") from exc
    wakeup.set()
    return retry


def recount(db: Session, job: BackgroundJob) -> None:
    rows = db.query(BackgroundJobItem).filter_by(job_id=job.job_id).all()
    job.total = len(rows)
    job.succeeded = sum(item.status == "succeeded" for item in rows)
    job.failed = sum(item.status == "failed" for item in rows)
    job.skipped = sum(item.status == "skipped" for item in rows)
    job.processed = job.succeeded + job.failed + job.skipped
    for key in ("scanned", "created", "scraped", "removed"):
        if key == "scanned" and job.kind == "scan" and not json.loads(job.params_json).get("retry_only"):
            continue
        setattr(job, key, sum(json.loads(item.result_json or "{}").get(key, 0) for item in rows if item.status == "succeeded"))
    job.waiting = (0 if json.loads(job.params_json).get("retry_only") else json.loads(job.scan_manifest_json or "{}").get("waiting", 0)) + sum(json.loads(item.result_json or "{}").get("waiting", 0) for item in rows)


def finish_item(db: Session, job: BackgroundJob, item: BackgroundJobItem,
                status: str, result: dict[str, int] | None = None, error: str | None = None, *, commit: bool = True) -> None:
    item.status, item.error = status, error
    item.result_json = json.dumps(result or {})
    job.processed += 1
    setattr(job, status, getattr(job, status) + 1)
    for key, value in (result or {}).items():
        setattr(job, key, getattr(job, key) + value)
    job.updated_at = utcnow()
    if commit:
        db.commit()


def add_item(db: Session, job: BackgroundJob, phase: str, key: str, label: str,
             *, path: str | None = None, media_id: int | None = None) -> None:
    db.add(BackgroundJobItem(job_id=job.job_id, item_key=key, phase=phase,
        label=label[:512], path=path, media_id=media_id))
    job.total += 1
