from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.config import get_settings
from app.deps import require_auth
from app.models import Library, MediaItem, FileObservation
from app.schemas import BrowseDirEntry, BrowseDirsOut, LibraryCreate, LibraryOut, LibraryUpdate, TaskOut
from app.services.actors import delete_orphan_actors
from app.services.fs_browse import BrowseError, list_subdirectories
from app.services import task_store
from app.api.tasks import conflict
from app.services.library_revision import get_revision
from app.services.watcher import reload_watches, watcher_status
from app.services.file_readiness import settle_seconds, ignored_dirs

router = APIRouter()


def _library_out(db: Session, lib: Library) -> LibraryOut:
    count = db.query(func.count(MediaItem.id)).filter(MediaItem.library_id == lib.id).scalar() or 0
    data = LibraryOut.model_validate(lib)
    state = next((entry for entry in watcher_status().get('libraries', []) if entry['id'] == lib.id), None)
    if state:
        data.watch_mode, data.watch_error = state['mode'], state['error']
    data.media_count = int(count)
    data.content_revision = get_revision(lib.id)
    data.effective_settle_seconds = settle_seconds(lib)
    data.effective_poll_interval_seconds = max(30, lib.scan_interval_seconds or get_settings().scan_poll_interval_seconds)
    data.effective_ignore_dirs = ",".join(sorted(ignored_dirs(lib)))
    data.waiting_files = db.query(func.count(FileObservation.id)).filter(FileObservation.library_id == lib.id, FileObservation.state.in_(("waiting", "unreadable"))).scalar() or 0
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
    lib = Library(**body.model_dump())
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
    for key in ("name", "path", "type", "enabled", "auto_scan_enabled", "scan_mode", "ts_policy"):
        if key in data and data[key] is None:
            raise HTTPException(422, f"{key} cannot be null")
    if "path" in data and data["path"] != lib.path and task_store.active_for_library(db, library_id):
        raise HTTPException(409, "请先取消或等待该媒体库的后台任务完成，再修改目录")
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
    if task_store.active_for_library(db, library_id):
        raise HTTPException(409, "请先取消或等待该媒体库的后台任务完成，再删除媒体库")
    db.delete(lib)
    db.flush()
    delete_orphan_actors(db)
    db.commit()
    reload_watches()


@router.post("/{library_id}/scan", response_model=TaskOut, status_code=202)
def scan_library(
    library_id: int,
    _: Annotated[dict, Depends(require_auth)],
    db: Session = Depends(get_db),
) -> TaskOut:
    lib = db.get(Library, library_id)
    if not lib:
        raise HTTPException(404, "library not found")
    try:
        return task_store.task_out(db, task_store.enqueue(db, "scan", lib))
    except task_store.TaskConflict as exc:
        raise conflict(exc) from exc


@router.post("/{library_id}/rescrape-pending", response_model=TaskOut, status_code=202)
def rescrape_pending_library(
    library_id: int,
    _: Annotated[dict, Depends(require_auth)],
    db: Session = Depends(get_db),
) -> TaskOut:
    """Scrape all unscraped items (with number) in the library — no filesystem scan."""
    lib = db.get(Library, library_id)
    if not lib:
        raise HTTPException(404, "library not found")
    try:
        return task_store.task_out(db, task_store.enqueue(db, "rescrape_pending", lib))
    except task_store.TaskConflict as exc:
        raise conflict(exc) from exc
