from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas import ScanJobOut
from app.services.jobs import job_store

router = APIRouter()


@router.get("/scan/jobs/{job_id}", response_model=ScanJobOut)
def get_scan_job(job_id: str) -> ScanJobOut:
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return ScanJobOut(**job.to_dict())
