from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Library
from app.schemas import LibraryCreate, LibraryOut, LibraryUpdate, ScanJobOut
from app.services.jobs import job_store
from app.services.scanner import run_scan_job

router = APIRouter()


@router.get("", response_model=list[LibraryOut])
def list_libraries(db: Session = Depends(get_db)) -> list[Library]:
    return db.query(Library).order_by(Library.id.asc()).all()


@router.post("", response_model=LibraryOut)
def create_library(body: LibraryCreate, db: Session = Depends(get_db)) -> Library:
    lib = Library(name=body.name, path=body.path, type=body.type, enabled=body.enabled)
    db.add(lib)
    db.commit()
    db.refresh(lib)
    return lib


@router.patch("/{library_id}", response_model=LibraryOut)
def update_library(library_id: int, body: LibraryUpdate, db: Session = Depends(get_db)) -> Library:
    lib = db.get(Library, library_id)
    if not lib:
        raise HTTPException(404, "library not found")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(lib, k, v)
    db.add(lib)
    db.commit()
    db.refresh(lib)
    return lib


@router.delete("/{library_id}", status_code=204)
def delete_library(library_id: int, db: Session = Depends(get_db)) -> None:
    lib = db.get(Library, library_id)
    if not lib:
        raise HTTPException(404, "library not found")
    db.delete(lib)
    db.commit()


@router.post("/{library_id}/scan", response_model=ScanJobOut)
def scan_library(
    library_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ScanJobOut:
    lib = db.get(Library, library_id)
    if not lib:
        raise HTTPException(404, "library not found")
    job = job_store.create(library_id)
    background_tasks.add_task(run_scan_job, job.job_id, library_id)
    return ScanJobOut(**job.to_dict())
