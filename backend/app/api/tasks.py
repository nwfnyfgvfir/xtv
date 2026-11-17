from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_auth
from app.models import BackgroundJob, BackgroundJobItem
from app.schemas import TaskItemOut, TaskOut
from app.services import task_store as store

def prevent_caching(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/tasks", dependencies=[Depends(require_auth), Depends(prevent_caching)])


def require_job(db: Session, job_id: str) -> BackgroundJob:
    job = db.get(BackgroundJob, job_id)
    if job is None:
        raise HTTPException(404, "task not found")
    return job


def conflict(exc: store.TaskConflict) -> HTTPException:
    return HTTPException(409, str(exc), headers={"X-Task-Id": exc.job_id} if exc.job_id else None)


@router.get("", response_model=list[TaskOut])
def list_tasks(db: Session = Depends(get_db), active_only: bool = False,
               library_id: int | None = None, media_id: int | None = None,
               limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    query = db.query(BackgroundJob)
    if active_only:
        query = query.filter(BackgroundJob.status.in_(store.ACTIVE))
    if library_id is not None:
        query = query.filter_by(library_id=library_id)
    if media_id is not None:
        query = query.filter_by(media_id=media_id)
    rows = query.order_by(BackgroundJob.created_at.desc(), BackgroundJob.job_id.desc()).offset(offset).limit(limit).all()
    return [store.task_out(db, job) for job in rows]


@router.delete('/history')
def clear_history(db: Session = Depends(get_db)):
    count = db.query(BackgroundJob).filter(BackgroundJob.status.in_(store.TERMINAL)).delete(synchronize_session=False)
    db.commit()
    return {'deleted': count}


@router.delete('/{job_id}', status_code=204)
def delete_history_item(job_id: str, db: Session = Depends(get_db)):
    require_job(db, job_id)
    count = db.query(BackgroundJob).filter(BackgroundJob.job_id == job_id,
        BackgroundJob.status.in_(store.TERMINAL)).delete(synchronize_session=False)
    if not count:
        raise HTTPException(409, '请先取消并等待任务停止，再删除记录')
    db.commit()


@router.get("/{job_id}", response_model=TaskOut)
def get_task(job_id: str, db: Session = Depends(get_db)):
    return store.task_out(db, require_job(db, job_id))


@router.get("/{job_id}/items", response_model=list[TaskItemOut])
def get_items(job_id: str, db: Session = Depends(get_db),
              status: str | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    require_job(db, job_id)
    query = db.query(BackgroundJobItem).filter_by(job_id=job_id)
    if status:
        query = query.filter_by(status=status)
    return [TaskItemOut(id=row.id, phase=row.phase, label=row.label, media_id=row.media_id,
        status=row.status, error=row.error) for row in query.order_by(BackgroundJobItem.id).offset(offset).limit(limit)]


@router.post("/{job_id}/{action}", response_model=TaskOut)
def control_task(job_id: str, action: str, db: Session = Depends(get_db)):
    operation = {"cancel": store.cancel, "resume": store.resume, "retry": store.retry_failed}.get(action)
    if operation is None:
        raise HTTPException(404, "unknown task action")
    try:
        job = operation(db, require_job(db, job_id))
        return store.task_out(db, job)
    except store.TaskConflict as exc:
        raise conflict(exc) from exc
