from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import require_auth
from app.db import get_db
from app.models import BackgroundJob
from app.schemas import ScanJobOut, TaskOut
from app.services.task_store import task_out
from app.services.jobs import job_store

router = APIRouter()


@router.get("/scan/jobs/{job_id}", response_model=TaskOut | ScanJobOut)
def get_scan_job(job_id: str, _: Annotated[dict, Depends(require_auth)], db: Session = Depends(get_db)) -> TaskOut | ScanJobOut:
    persistent = db.get(BackgroundJob, job_id)
    if persistent:
        return task_out(db, persistent)
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return ScanJobOut(**job.to_dict())
