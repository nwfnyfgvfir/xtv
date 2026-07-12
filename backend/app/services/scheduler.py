from __future__ import annotations

import logging
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.db import SessionLocal
from app.models import Library
from app.services.jobs import job_store
from app.services.scanner import run_scan_job

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
_MIN_SECONDS = 30


def _interval_seconds(lib: Library) -> int:
    if lib.scan_interval_seconds and lib.scan_interval_seconds > 0:
        return max(_MIN_SECONDS, int(lib.scan_interval_seconds))
    if lib.scan_interval_hours and lib.scan_interval_hours > 0:
        return max(_MIN_SECONDS, int(lib.scan_interval_hours) * 3600)
    return 86400


def _scan_library_task(library_id: int) -> None:
    job = job_store.create(library_id)
    logger.info("Scheduled scan start library=%s job=%s", library_id, job.job_id)
    run_scan_job(job.job_id, library_id)
    logger.info("Scheduled scan finished library=%s status=%s", library_id, job.status)


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.start()
    reload_library_jobs()
    logger.info("APScheduler started")


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None
    logger.info("APScheduler stopped")


def reload_library_jobs() -> None:
    if _scheduler is None:
        return
    for job in list(_scheduler.get_jobs()):
        if str(job.id).startswith("libscan-"):
            job.remove()

    db = SessionLocal()
    try:
        libs = (
            db.query(Library)
            .filter(Library.enabled.is_(True), Library.auto_scan_enabled.is_(True))
            .all()
        )
        for lib in libs:
            secs = _interval_seconds(lib)
            job_id = f"libscan-{lib.id}"
            _scheduler.add_job(
                _scan_library_task,
                trigger=IntervalTrigger(seconds=secs),
                id=job_id,
                args=[lib.id],
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            logger.info("Registered auto-scan library=%s every %ss", lib.id, secs)
    finally:
        db.close()


def scheduler_status() -> dict[str, Any]:
    if _scheduler is None:
        return {"running": False, "jobs": []}
    jobs = []
    for j in _scheduler.get_jobs():
        jobs.append(
            {
                "id": j.id,
                "next_run_time": j.next_run_time.isoformat() if j.next_run_time else None,
            }
        )
    return {"running": True, "jobs": jobs}
