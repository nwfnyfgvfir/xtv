from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_auth
from app.models import Library, MediaItem
from app.schemas import BrowseDirEntry, BrowseDirsOut, LibraryCreate, LibraryOut, LibraryUpdate, ScanJobOut
from app.services.actors import delete_orphan_actors
from app.services.fs_browse import BrowseError, list_subdirectories
from app.services.jobs import job_store
from app.services.library_revision import get_revision
from app.services.scanner import run_rescrape_pending_job, run_scan_job
from app.services.watcher import reload_watches

router = APIRouter()


def _library_out(db: Session, lib: Library) -> LibraryOut:
    count = db.query(func.count(MediaItem.id)).filter(MediaItem.library_id == lib.id).scalar() or 0
    data = LibraryOut.model_validate(lib)
    data.media_count = int(count)
    data.content_revision = get_revision(lib.id)
    return data


@router.get("/browse", response_model=BrowseDirsOut)
def browse_directories(
    _: Annotated[dict, Depends(require_auth)],
    path: str = "",
) -> BrowseDirsOut:
    """List subdirectories under MEDIA_ROOT for the library path picker."""
    try:
        result = list_subdirectories(path)
    except BrowseError as e:
        raise HTTPException(e.status_code, e.message) from e
    return BrowseDirsOut(
        path=result.path,
        parent=result.parent,
        directories=[BrowseDirEntry(name=d.name, path=d.path) for d in result.directories],
    )


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
    lib = Library(
        name=body.name,
        path=body.path,
        type=body.type,
        enabled=body.enabled,
    )
    db.add(lib)
    db.commit()
    db.refresh(lib)
    reload_watches()
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
    for k, v in data.items():
        setattr(lib, k, v)
    db.add(lib)
    db.commit()
    db.refresh(lib)
    reload_watches()
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
    reload_watches()


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


@router.post("/{library_id}/rescrape-pending", response_model=ScanJobOut)
def rescrape_pending_library(
    library_id: int,
    background_tasks: BackgroundTasks,
    _: Annotated[dict, Depends(require_auth)],
    db: Session = Depends(get_db),
) -> ScanJobOut:
    """Scrape all unscraped items (with number) in the library — no filesystem scan."""
    lib = db.get(Library, library_id)
    if not lib:
        raise HTTPException(404, "library not found")
    job = job_store.create(library_id)
    background_tasks.add_task(run_rescrape_pending_job, job.job_id, library_id)
    return ScanJobOut(**job.to_dict())
