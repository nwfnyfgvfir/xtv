"""Delete local media: disk file (+ sidecars) then DB row."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Library, MediaItem
from app.services.actors import delete_orphan_actors
from app.services.library_revision import bump_revision
from app.services.scanner import resolve_library_path
from app.services.subtitles import discover_sidecar_subtitles

logger = logging.getLogger(__name__)


def ensure_media_path_allowed(item: MediaItem, db: Session) -> Path:
    """Resolve item.path and ensure it lies under the library root or MEDIA_ROOT.

    Unlike playback's helper, missing files are allowed (caller may still drop the DB row).
    """
    lib = db.get(Library, item.library_id)
    if not lib:
        raise HTTPException(404, "library missing")
    root = resolve_library_path(lib)
    path = Path(item.path).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        media_root = get_settings().media_root_path.resolve()
        try:
            path.relative_to(media_root)
        except ValueError:
            raise HTTPException(403, "path outside library root") from exc
    return path


def unlink_local_media_files(path: Path) -> None:
    """Delete the media file and same-dir sidecar subtitles.

    Raises OSError if the main file exists but cannot be removed (DB must not be deleted then).
    Sidecar failures are logged and ignored.
    """
    if path.is_file():
        sidecars = discover_sidecar_subtitles(path)
        path.unlink()
        for sub in sidecars:
            try:
                sub.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("failed to delete sidecar %s: %s", sub, exc)
    elif path.exists():
        # Path exists but is not a regular file — refuse to avoid surprising deletes.
        raise HTTPException(400, f"not a regular file: {path}")


def delete_local_media(db: Session, item: MediaItem) -> None:
    """Delete local media file (if present) and remove the DB row.

    Requires ``source_type == "local"``. Path must be under library/MEDIA_ROOT.
    """
    if (item.source_type or "").lower() != "local":
        raise HTTPException(400, "only local media can be deleted")

    path = ensure_media_path_allowed(item, db)
    library_id = item.library_id

    try:
        unlink_local_media_files(path)
    except HTTPException:
        raise
    except OSError as exc:
        logger.exception("failed to delete media file %s", path)
        raise HTTPException(500, f"failed to delete file: {exc}") from exc

    db.delete(item)
    db.flush()
    delete_orphan_actors(db)
    db.commit()
    bump_revision(library_id)


def delete_media_index(db: Session, item: MediaItem) -> None:
    """Remove the library index row only (no disk unlink).

    Suitable for ``strm`` and other non-local entries. A later scan may re-ingest
    the file if it still exists under the library path.
    """
    library_id = item.library_id
    db.delete(item)
    db.flush()
    delete_orphan_actors(db)
    db.commit()
    bump_revision(library_id)


def delete_media_item(db: Session, item: MediaItem) -> None:
    """Unified delete: local files + index; non-local index only."""
    if (item.source_type or "").lower() == "local":
        delete_local_media(db, item)
    else:
        delete_media_index(db, item)
