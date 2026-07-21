from __future__ import annotations

import mimetypes
import re
from datetime import datetime, timezone
from pathlib import Path

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_auth
from app.models import MediaItem, PlaybackProgress
from app.schemas import PlayInfo, ProgressIn, ProgressOut, SubtitleTrack
from app.services.scanner import resolve_library_path
from app.services.subtitles import build_subtitle_tracks, mime_for_subtitle, resolve_sidecar_file

router = APIRouter()


def _local_subtitles(item: MediaItem) -> list[SubtitleTrack]:
    """Discover sidecar tracks when the media file is present; never fail play_info."""
    try:
        path = Path(item.path)
        if not path.is_file():
            return []
        return [SubtitleTrack.model_validate(t) for t in build_subtitle_tracks(item.id, path)]
    except Exception:  # noqa: BLE001
        return []


def _ensure_path_in_library(item: MediaItem, db: Session) -> Path:
    from app.models import Library

    lib = db.get(Library, item.library_id)
    if not lib:
        raise HTTPException(404, "library missing")
    root = resolve_library_path(lib)
    path = Path(item.path).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        # also allow if path is under media_root
        from app.config import get_settings

        media_root = get_settings().media_root_path
        try:
            path.relative_to(media_root)
        except ValueError:
            raise HTTPException(403, "path outside library root") from exc
    if not path.is_file():
        raise HTTPException(404, f"file missing: {path}")
    return path


@router.get("/media/{media_id}/play", response_model=PlayInfo)
async def play_info(
    media_id: int,
    _: Annotated[dict, Depends(require_auth)],
    db: Session = Depends(get_db),
) -> PlayInfo:
    item = db.get(MediaItem, media_id)
    if not item:
        raise HTTPException(404, "media not found")

    is_strm = (item.filename or "").lower().endswith(".strm") or bool(item.strm_target)
    if not is_strm and item.source_type == "local":
        return PlayInfo(
            play_url=f"/api/stream/{item.id}",
            kind="local",
            subtitles=_local_subtitles(item),
        )

    target = (item.strm_target or "").strip()
    if not target and is_strm:
        from app.services.strm import read_strm_target

        target = read_strm_target(Path(item.path)) or ""

    if not target:
        # fallback to local stream if file is a real video
        if not is_strm:
            return PlayInfo(
                play_url=f"/api/stream/{item.id}",
                kind="local",
                subtitles=_local_subtitles(item),
            )
        raise HTTPException(404, "empty strm target")

    if target.lower().startswith("http://") or target.lower().startswith("https://"):
        return PlayInfo(play_url=target, kind="direct", subtitles=[])

    raise HTTPException(400, "不支持的 .strm 目标（仅支持 http/https 直链）")


@router.get("/stream/{media_id}")
async def stream_media(media_id: int, request: Request, db: Session = Depends(get_db)):
    item = db.get(MediaItem, media_id)
    if not item:
        raise HTTPException(404, "media not found")
    if (item.filename or "").lower().endswith(".strm"):
        raise HTTPException(400, "use /play for strm files")

    path = _ensure_path_in_library(item, db)
    file_size = path.stat().st_size
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    range_header = request.headers.get("range")

    if not range_header:
        return FileResponse(path, media_type=content_type, filename=path.name)

    m = re.match(r"bytes=(\d*)-(\d*)", range_header)
    if not m:
        raise HTTPException(416, "invalid range")
    start_s, end_s = m.group(1), m.group(2)
    start = int(start_s) if start_s else 0
    end = int(end_s) if end_s else file_size - 1
    if start >= file_size:
        raise HTTPException(416, "range start beyond file")
    end = min(end, file_size - 1)
    length = end - start + 1

    def iterfile():
        with path.open("rb") as f:
            f.seek(start)
            remaining = length
            chunk = 1024 * 1024
            while remaining > 0:
                data = f.read(min(chunk, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
    }
    return StreamingResponse(iterfile(), status_code=206, media_type=content_type, headers=headers)


@router.get("/stream/{media_id}/subtitle")
async def stream_subtitle(
    media_id: int,
    file: str = Query(..., min_length=1, max_length=512),
    db: Session = Depends(get_db),
):
    """Serve a same-directory sidecar subtitle (no auth — Artplayer fetches without JWT)."""
    item = db.get(MediaItem, media_id)
    if not item:
        raise HTTPException(404, "media not found")
    if (item.filename or "").lower().endswith(".strm"):
        raise HTTPException(400, "subtitles not available for strm")

    media_path = _ensure_path_in_library(item, db)
    try:
        sub_path = resolve_sidecar_file(media_path, file)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    return FileResponse(
        sub_path,
        media_type=mime_for_subtitle(sub_path),
        filename=sub_path.name,
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/media/{media_id}/progress", response_model=ProgressOut)
def get_progress(
    media_id: int,
    _: Annotated[dict, Depends(require_auth)],
    db: Session = Depends(get_db),
) -> ProgressOut:
    item = db.get(MediaItem, media_id)
    if not item:
        raise HTTPException(404, "media not found")
    prog = db.query(PlaybackProgress).filter(PlaybackProgress.media_id == media_id).one_or_none()
    if not prog:
        return ProgressOut(media_id=media_id, position_sec=0, duration_sec=None, updated_at=None)
    return ProgressOut(
        media_id=media_id,
        position_sec=prog.position_sec,
        duration_sec=prog.duration_sec,
        updated_at=prog.updated_at,
    )


@router.put("/media/{media_id}/progress", response_model=ProgressOut)
def put_progress(
    media_id: int,
    body: ProgressIn,
    _: Annotated[dict, Depends(require_auth)],
    db: Session = Depends(get_db),
) -> ProgressOut:
    item = db.get(MediaItem, media_id)
    if not item:
        raise HTTPException(404, "media not found")
    prog = db.query(PlaybackProgress).filter(PlaybackProgress.media_id == media_id).one_or_none()
    if not prog:
        prog = PlaybackProgress(media_id=media_id)
    prog.position_sec = max(0.0, body.position_sec)
    prog.duration_sec = body.duration_sec
    prog.updated_at = datetime.now(timezone.utc)
    db.add(prog)
    db.commit()
    db.refresh(prog)
    return ProgressOut(
        media_id=media_id,
        position_sec=prog.position_sec,
        duration_sec=prog.duration_sec,
        updated_at=prog.updated_at,
    )


@router.get("/images/proxy")
async def proxy_image(url: str = Query(..., min_length=8)):
    """Same-origin image proxy with SSRF guards, memory LRU and optional disk cache (no auth — for <img>)."""
    import httpx
    from fastapi.responses import Response

    from app.config import get_settings
    from app.services.images import (
        cache_get,
        cache_set,
        disk_cache_get,
        disk_cache_set,
        validate_proxy_url,
    )

    try:
        url = validate_proxy_url(url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    headers = {"Cache-Control": "public, max-age=3600"}

    cached = cache_get(url)
    if cached:
        ctype, body = cached
        return Response(content=body, media_type=ctype, headers=headers)

    settings = get_settings()
    if settings.image_local_cache:
        disk = disk_cache_get(url)
        if disk:
            ctype, body = disk
            if len(body) <= 5 * 1024 * 1024:
                cache_set(url, ctype, body)
            return Response(
                content=body,
                media_type=ctype,
                headers={**headers, "Cache-Control": "public, max-age=604800"},
            )

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": "TV-App/0.2",
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                },
            )
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"upstream fetch failed: {exc}") from exc
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, "upstream image error")
    content_type = resp.headers.get("content-type", "image/jpeg")
    if "image" not in content_type and "octet-stream" not in content_type:
        # still allow (some CDNs return wrong types)
        content_type = content_type or "image/jpeg"
    body = resp.content
    if len(body) <= 5 * 1024 * 1024:
        cache_set(url, content_type, body)
        if settings.image_local_cache:
            disk_cache_set(url, content_type, body)
    return Response(content=body, media_type=content_type, headers=headers)
