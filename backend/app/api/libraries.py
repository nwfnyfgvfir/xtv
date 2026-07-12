from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_auth
from app.models import Library, MediaItem
from app.schemas import LibraryCreate, LibraryOut, LibraryUpdate, ScanJobOut
from app.services.actors import delete_orphan_actors
from app.services.jobs import job_store
from app.services.library_revision import get_revision
from app.services.scanner import run_scan_job
from app.services.scheduler import reload_library_jobs

router = APIRouter()


def _library_out(db: Session, lib: Library) -> LibraryOut:
    count = db.query(func.count(MediaItem.id)).filter(MediaItem.library_id == lib.id).scalar() or 0
    data = LibraryOut.model_validate(lib)
    data.media_count = int(count)
    data.content_revision = get_revision(lib.id)
    return data


@router.get("", response_model=list[LibraryOut])
def list_libraries(
    _: Annotated[dict, Depends(require_auth)],
    db: Session = Depends(get_db),
) -> list[LibraryOut]:
    libs = db.query(Library).order_by(Library.id.asc()).all()
    return [_library_out(db, lib) for lib in libs]


@router.post("", response_model=LibraryOut)
def create_library(
    body: LibraryCreate,
    _: Annotated[dict, Depends(require_auth)],
    db: Session = Depends(get_db),
) -> LibraryOut:
    secs = body.scan_interval_seconds
    if secs is None and body.scan_interval_hours:
        secs = body.scan_interval_hours * 3600
    lib = Library(
        name=body.name,
        path=body.path,
        type=body.type,
        enabled=body.enabled,
        auto_scan_enabled=body.auto_scan_enabled,
        scan_interval_hours=body.scan_interval_hours,
        scan_interval_seconds=secs,
    )
    db.add(lib)
    db.commit()
    db.refresh(lib)
    reload_library_jobs()
    return _library_out(db, lib)


@router.patch("/{library_id}", response_model=LibraryOut)
def update_library(
    library_id: int,
    body: LibraryUpdate,
    _: Annotated[dict, Depends(require_auth)],
    db: Session = Depends(get_db),
) -> LibraryOut:
    lib = db.get(Library, library_id)
    if not lib:
        raise HTTPException(404, "library not found")
    data = body.model_dump(exclude_unset=True)
    if "scan_interval_seconds" not in data and data.get("scan_interval_hours"):
        data["scan_interval_seconds"] = int(data["scan_interval_hours"]) * 3600
    for k, v in data.items():
        setattr(lib, k, v)
    db.add(lib)
    db.commit()
    db.refresh(lib)
    reload_library_jobs()
    return _library_out(db, lib)


@router.delete("/{library_id}", status_code=204)
def delete_library(
    library_id: int,
    _: Annotated[dict, Depends(require_auth)],
    db: Session = Depends(get_db),
) -> None:
    lib = db.get(Library, library_id)
    if not lib:
        raise HTTPException(404, "library not found")
    db.delete(lib)
    db.flush()
    delete_orphan_actors(db)
    db.commit()
    reload_library_jobs()


@router.post("/{library_id}/scan", response_model=ScanJobOut)
def scan_library(
    library_id: int,
    background_tasks: BackgroundTasks,
    _: Annotated[dict, Depends(require_auth)],
    db: Session = Depends(get_db),
) -> ScanJobOut:
    lib = db.get(Library, library_id)
    if not lib:
        raise HTTPException(404, "library not found")
    job = job_store.create(library_id)
    background_tasks.add_task(run_scan_job, job.job_id, library_id)
    return ScanJobOut(**job.to_dict())
