from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.tasks import prevent_caching, conflict
from app.db import get_db
from app.deps import require_auth
from app.models import Library, MediaItem, FileObservation
from app.schemas import TaskOut
from app.services.file_readiness import check_file, root_path
from app.services import task_store

router = APIRouter(dependencies=[Depends(require_auth), Depends(prevent_caching)])


def library(db, library_id):
    lib = db.get(Library, library_id)
    if lib is None:
        raise HTTPException(404, "library not found")
    return lib


@router.get("/{library_id}/cleanup-preview")
def cleanup_preview(library_id: int, cursor: int = Query(0, ge=0), db: Session = Depends(get_db)):
    lib = library(db, library_id)
    if not root_path(lib).is_dir():
        raise HTTPException(503, "媒体库目录暂不可访问，无法进行清理预览")
    rows = db.query(MediaItem).filter(MediaItem.library_id == lib.id, MediaItem.id > cursor).order_by(MediaItem.id).limit(500).all()
    items = []
    last = cursor
    scanned = 0
    for row in rows:
        last, scanned = row.id, scanned + 1
        check = check_file(db, lib, Path(row.path), readonly=True)
        if check.state not in {"ready", "missing"}:
            items.append({"id": row.id, "filename": row.filename, "path": row.path,
                "state": check.state, "reason": check.reason, "number": row.number})
        if len(items) == 50:
            break
    more = db.query(MediaItem.id).filter(MediaItem.library_id == lib.id, MediaItem.id > last).first() is not None
    total = db.query(func.count(MediaItem.id)).filter_by(library_id=lib.id).scalar()
    return {"items": items, "scanned": scanned, "total_indexed": total,
        "next_cursor": last if more else None, "read_only": True}


@router.get("/{library_id}/waiting")
def waiting_files(library_id: int, offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    library(db, library_id)
    query = db.query(FileObservation).filter(FileObservation.library_id == library_id,
        FileObservation.state.in_(("waiting", "unreadable")))
    return {"total": query.count(), "items": [{"path": row.path, "filename": Path(row.path).name,
        "state": row.state, "reason": row.reason, "next_check_at": row.next_check_at} for row in query.order_by(FileObservation.id).offset(offset).limit(50)]}


@router.post("/{library_id}/recheck", response_model=TaskOut, status_code=202)
def recheck_waiting(library_id: int, db: Session = Depends(get_db)):
    lib = library(db, library_id)
    paths = [path for path, in db.query(FileObservation.path).filter(FileObservation.library_id == library_id,
        FileObservation.state.in_(("waiting", "unreadable")))]
    if not paths:
        raise HTTPException(409, "没有等待就绪的文件")
    try:
        return task_store.task_out(db, task_store.enqueue(db, "scan", lib, inputs={"paths": paths}))
    except task_store.TaskConflict as exc:
        raise conflict(exc) from exc


class CompletionIn(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=100)


@router.post("/{library_id}/download-complete", response_model=TaskOut, status_code=202)
def download_complete(library_id: int, body: CompletionIn, db: Session = Depends(get_db)):
    lib = library(db, library_id)
    root = root_path(lib)
    paths = []
    for raw in body.paths:
        path = (root / raw).resolve()
        if not path.is_relative_to(root):
            raise HTTPException(400, "完成通知路径必须在媒体库内")
        if str(path) in paths:
            continue
        check = check_file(db, lib, path, confirmed=True)
        if check.state != "ready":
            raise HTTPException(409, check.reason)
        paths.append(str(path))
    db.commit()
    try:
        return task_store.task_out(db, task_store.enqueue(db, "scan", lib, inputs={"paths": paths}))
    except task_store.TaskConflict as exc:
        raise conflict(exc) from exc
