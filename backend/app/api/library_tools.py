from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.tasks import prevent_caching, conflict
from app.db import get_db
from app.deps import require_auth
from app.models import Library
from app.schemas import TaskOut
from app.services.scan_files import root_path
from app.services import task_store

router = APIRouter(dependencies=[Depends(require_auth), Depends(prevent_caching)])


def library(db, library_id):
    lib = db.get(Library, library_id)
    if lib is None:
        raise HTTPException(404, "library not found")
    return lib


class CompletionIn(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=100)


@router.post("/{library_id}/download-complete", response_model=TaskOut, status_code=202)
def download_complete(library_id: int, body: CompletionIn, db: Session = Depends(get_db)):
    lib = library(db, library_id)
    root = root_path(lib)
    paths = []
    for raw in body.paths:
        path = (root / raw).resolve()
        if path.parent != root:
            raise HTTPException(400, "完成通知路径必须位于媒体库根目录")
        if str(path) in paths:
            continue
        if not path.is_file():
            raise HTTPException(409, "文件不存在")
        paths.append(str(path))
    db.commit()
    try:
        return task_store.task_out(db, task_store.enqueue(db, "scan", lib, inputs={"paths": paths}))
    except task_store.TaskConflict as exc:
        raise conflict(exc) from exc
