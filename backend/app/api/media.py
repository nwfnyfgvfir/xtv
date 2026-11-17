from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.deps import require_auth
from app.models import Favorite, Library, MediaItem
from app.api.tasks import conflict
from app.services import task_store
from app.schemas import (
    BatchDeleteFailure,
    BatchDeleteIn,
    BatchDeleteResult,
    MediaDetail,
    MediaListItem,
    MediaListQuery,
    PaginatedDuplicateGroups,
    PaginatedMedia,
    RenameIn,
    RescrapeIn,
    TaskOut,
)
from app.services.duplicates import list_duplicate_groups
from app.services.images import rewrite_image_url
from app.services.media_delete import delete_media_item
from app.services.naming import source_name
from app.services.file_readiness import check_file
from app.services.scanner import rename_media_item
from app.services.scrape import apply_translations, scrape_media_item
from app.services.sorting import media_order_by

router = APIRouter()


def _with_proxied_images(
    item: MediaItem,
    *,
    detail: bool = False,
    favorited: bool | None = None,
) -> MediaListItem | MediaDetail:
    model = MediaDetail if detail else MediaListItem
    data = model.model_validate(item)
    data.number = source_name(item.filename)
    data.cover_url = rewrite_image_url(
        data.cover_url, provider=item.provider, provider_id=item.provider_id
    )
    data.thumb_url = rewrite_image_url(
        data.thumb_url, provider=item.provider, provider_id=item.provider_id
    )
    if detail and isinstance(data, MediaDetail):
        data.backdrop_url = rewrite_image_url(
            data.backdrop_url, provider=item.provider, provider_id=item.provider_id
        )
        data.actors = [
            a.model_copy(update={"image_url": rewrite_image_url(a.image_url)}) for a in data.actors
        ]
    if favorited is None:
        favorited = item.favorite is not None
    data.favorited = bool(favorited)
    return data


@router.get("/duplicates", response_model=PaginatedDuplicateGroups)
def list_duplicates(
    _: Annotated[dict, Depends(require_auth)],
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
) -> PaginatedDuplicateGroups:
    """List groups of media that share the same 番号 (case-insensitive)."""
    return list_duplicate_groups(db, page=page, page_size=page_size, q=q)


@router.post("/batch-delete", response_model=BatchDeleteResult)
def batch_delete_media(
    body: BatchDeleteIn,
    _: Annotated[dict, Depends(require_auth)],
    db: Session = Depends(get_db),
) -> BatchDeleteResult:
    """Delete selected media; local removes files, non-local drops index only."""
    deleted: list[int] = []
    failed: list[BatchDeleteFailure] = []
    # Dedupe while preserving order
    seen: set[int] = set()
    ids: list[int] = []
    for mid in body.ids:
        if mid not in seen:
            seen.add(mid)
            ids.append(mid)

    for media_id in ids:
        item = db.get(MediaItem, media_id)
        if not item:
            failed.append(BatchDeleteFailure(id=media_id, error="media not found"))
            continue
        try:
            delete_media_item(db, item)
            deleted.append(media_id)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            failed.append(BatchDeleteFailure(id=media_id, error=detail))
        except Exception as exc:  # noqa: BLE001 — partial success for batch
            failed.append(BatchDeleteFailure(id=media_id, error=str(exc)))
    return BatchDeleteResult(deleted=deleted, failed=failed)


def _list_media_page(
    db: Session,
    *,
    q: str | None = None,
    library_id: int | None = None,
    scraped: bool | None = None,
    favorited: bool | None = None,
    subtitle_flag: str | None = None,
    sort: str | None = None,
    page: int = 1,
    page_size: int = 40,
) -> PaginatedMedia:
    query = db.query(MediaItem)
    if library_id is not None:
        query = query.filter(MediaItem.library_id == library_id)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                MediaItem.title.ilike(like),
                MediaItem.number.ilike(like),
                MediaItem.filename.ilike(like),
            )
        )
    if scraped is True:
        query = query.filter(MediaItem.scraped_at.isnot(None))
    elif scraped is False:
        query = query.filter(MediaItem.scraped_at.is_(None))
    if favorited is True:
        query = query.join(Favorite, Favorite.media_id == MediaItem.id)
    elif favorited is False:
        query = query.outerjoin(Favorite, Favorite.media_id == MediaItem.id).filter(Favorite.id.is_(None))
    if subtitle_flag:
        query = query.filter(MediaItem.subtitle_flag == subtitle_flag)

    total = query.with_entities(func.count(MediaItem.id)).scalar() or 0
    items = (
        query.options(joinedload(MediaItem.favorite))
        .order_by(*media_order_by(sort))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedMedia(
        items=[_with_proxied_images(i) for i in items],  # type: ignore[list-item]
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("", response_model=PaginatedMedia)
def list_media(
    _: Annotated[dict, Depends(require_auth)],
    q: str | None = None,
    library_id: int | None = None,
    scraped: bool | None = None,
    favorited: bool | None = None,
    subtitle_flag: str | None = Query(None, description="e.g. C for Chinese subtitle"),
    sort: str | None = Query(None, description="number_asc|number_desc|created_asc|created_desc|release_asc|release_desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(40, ge=1, le=200),
    db: Session = Depends(get_db),
) -> PaginatedMedia:
    return _list_media_page(
        db,
        q=q,
        library_id=library_id,
        scraped=scraped,
        favorited=favorited,
        subtitle_flag=subtitle_flag,
        sort=sort,
        page=page,
        page_size=page_size,
    )


@router.get("/query/{cache_buster}", response_model=PaginatedMedia)
def query_media_with_cache_buster(
    cache_buster: str,
    _: Annotated[dict, Depends(require_auth)],
    q: str | None = None,
    library_id: int | None = None,
    scraped: bool | None = None,
    favorited: bool | None = None,
    subtitle_flag: str | None = Query(None, description="e.g. C for Chinese subtitle"),
    sort: str | None = Query(None, description="number_asc|number_desc|created_asc|created_desc|release_asc|release_desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(40, ge=1, le=200),
    db: Session = Depends(get_db),
) -> PaginatedMedia:
    _ = cache_buster
    return _list_media_page(
        db,
        q=q,
        library_id=library_id,
        scraped=scraped,
        favorited=favorited,
        subtitle_flag=subtitle_flag,
        sort=sort,
        page=page,
        page_size=page_size,
    )


@router.post("/query", response_model=PaginatedMedia)
def query_media(
    body: MediaListQuery,
    _: Annotated[dict, Depends(require_auth)],
    db: Session = Depends(get_db),
) -> PaginatedMedia:
    return _list_media_page(
        db,
        q=body.q,
        library_id=body.library_id,
        scraped=body.scraped,
        favorited=body.favorited,
        subtitle_flag=body.subtitle_flag,
        sort=body.sort,
        page=body.page,
        page_size=body.page_size,
    )


@router.get("/{media_id}", response_model=MediaDetail)
def get_media(
    media_id: int,
    _: Annotated[dict, Depends(require_auth)],
    db: Session = Depends(get_db),
) -> MediaDetail:
    item = (
        db.query(MediaItem)
        .options(joinedload(MediaItem.actors), joinedload(MediaItem.favorite))
        .filter(MediaItem.id == media_id)
        .one_or_none()
    )
    if not item:
        raise HTTPException(404, "media not found")
    return _with_proxied_images(item, detail=True)  # type: ignore[return-value]


@router.post("/{media_id}/rescrape-task", response_model=TaskOut, status_code=202)
def enqueue_rescrape(media_id: int, _: Annotated[dict, Depends(require_auth)],
                     body: RescrapeIn | None = None, db: Session = Depends(get_db)) -> TaskOut:
    from urllib.parse import urlsplit
    from app.config import get_settings

    item = db.get(MediaItem, media_id)
    if item is None:
        raise HTTPException(404, "media not found")
    body = body or RescrapeIn()
    inputs = body.model_dump(exclude_none=True)
    url = (body.url or "").strip()
    if url:
        if get_settings().scrape_source not in {"stash", "stashscrapers"}:
            raise HTTPException(400, "source URL scraping requires Stash or StashScrapers")
        try:
            parts = urlsplit(url)
            if parts.scheme not in {"http", "https"} or not parts.hostname:
                raise ValueError()
        except ValueError:
            raise HTTPException(400, "invalid source URL") from None
        inputs["url"] = url
    try:
        return task_store.task_out(db, task_store.enqueue(db, "rescrape", db.get(Library, item.library_id),
            media_id=media_id, inputs=inputs))
    except task_store.TaskConflict as exc:
        raise conflict(exc) from exc


@router.post("/{media_id}/rescrape", response_model=MediaDetail, deprecated=True)
async def rescrape_media(
    media_id: int,
    _: Annotated[dict, Depends(require_auth)],
    db: Session = Depends(get_db),
    body: RescrapeIn | None = None,
) -> MediaDetail:
    item = (
        db.query(MediaItem)
        .options(joinedload(MediaItem.actors), joinedload(MediaItem.favorite))
        .filter(MediaItem.id == media_id)
        .one_or_none()
    )
    if not item:
        raise HTTPException(404, "media not found")
    if task_store.active_for_library(db, item.library_id):
        raise HTTPException(409, "该媒体库已有后台任务，请先取消或等待完成")
    body = body or RescrapeIn()
    source_url = (body.url or "").strip()
    if source_url:
        from urllib.parse import urlsplit
        from app.config import get_settings

        if get_settings().scrape_source not in {"stash", "stashscrapers"}:
            raise HTTPException(400, "source URL scraping requires Stash or StashScrapers")
        try:
            parsed = urlsplit(source_url)
            valid_url = parsed.scheme in {"http", "https"} and bool(parsed.hostname)
        except ValueError:
            valid_url = False
        if not valid_url:
            raise HTTPException(400, "invalid source URL")
    lib = db.get(Library, item.library_id)
    if Path(item.path).exists():
        readiness = check_file(db, lib, Path(item.path))
        db.commit()
        if readiness.state != "ready":
            raise HTTPException(409, readiness.reason)
    ok = await scrape_media_item(
        db,
        item,
        force=True,
        provider_override=body.provider,
        url_override=source_url or None,
    )
    db.refresh(item)
    if not ok:
        raise HTTPException(502, "scrape failed or no results")
    item = (
        db.query(MediaItem)
        .options(joinedload(MediaItem.actors), joinedload(MediaItem.favorite))
        .filter(MediaItem.id == media_id)
        .one()
    )
    return _with_proxied_images(item, detail=True)  # type: ignore[return-value]


@router.post("/{media_id}/translate", response_model=MediaDetail)
async def translate_media(
    media_id: int,
    _: Annotated[dict, Depends(require_auth)],
    db: Session = Depends(get_db),
) -> MediaDetail:
    """Translate existing title/plot/tags without re-scraping MetaTube.

    Always runs (ignores ``auto_translate``). Source text prefers
    ``title_original`` / ``plot_original``, then current display fields.
    """
    item = (
        db.query(MediaItem)
        .options(joinedload(MediaItem.actors), joinedload(MediaItem.favorite))
        .filter(MediaItem.id == media_id)
        .one_or_none()
    )
    if not item:
        raise HTTPException(404, "media not found")

    src_title = (item.title_original or item.title or "").strip() or None
    src_plot = (item.plot_original or item.plot or "").strip() or None
    tags: list[str] = []
    if item.tags_json:
        try:
            raw = json.loads(item.tags_json)
            if isinstance(raw, list):
                tags = [str(t) for t in raw if str(t).strip()]
        except (json.JSONDecodeError, TypeError):
            tags = []

    if not src_title and not src_plot and not tags:
        raise HTTPException(400, "nothing to translate")

    # Reset display fields to source language so re-translate uses originals.
    if src_title:
        item.title = src_title
    if src_plot:
        item.plot = src_plot

    await apply_translations(
        db,
        item,
        src_title=src_title,
        src_plot=src_plot,
        tags=tags,
    )
    db.add(item)
    db.commit()

    item = (
        db.query(MediaItem)
        .options(joinedload(MediaItem.actors), joinedload(MediaItem.favorite))
        .filter(MediaItem.id == media_id)
        .one()
    )
    return _with_proxied_images(item, detail=True)  # type: ignore[return-value]


@router.delete("/{media_id}", status_code=204)
def delete_media(
    media_id: int,
    _: Annotated[dict, Depends(require_auth)],
    db: Session = Depends(get_db),
) -> None:
    """Delete local media file + index, or index-only for non-local (e.g. strm)."""
    item = db.get(MediaItem, media_id)
    if not item:
        raise HTTPException(404, "media not found")
    delete_media_item(db, item)


@router.post("/{media_id}/favorite", response_model=MediaDetail)
def favorite_media(
    media_id: int,
    _: Annotated[dict, Depends(require_auth)],
    db: Session = Depends(get_db),
) -> MediaDetail:
    item = (
        db.query(MediaItem)
        .options(joinedload(MediaItem.actors), joinedload(MediaItem.favorite))
        .filter(MediaItem.id == media_id)
        .one_or_none()
    )
    if not item:
        raise HTTPException(404, "media not found")
    if item.favorite is None:
        db.add(Favorite(media_id=media_id))
        db.commit()
        item = (
            db.query(MediaItem)
            .options(joinedload(MediaItem.actors), joinedload(MediaItem.favorite))
            .filter(MediaItem.id == media_id)
            .one()
        )
    return _with_proxied_images(item, detail=True)  # type: ignore[return-value]


@router.delete("/{media_id}/favorite", response_model=MediaDetail)
def unfavorite_media(
    media_id: int,
    _: Annotated[dict, Depends(require_auth)],
    db: Session = Depends(get_db),
) -> MediaDetail:
    item = (
        db.query(MediaItem)
        .options(joinedload(MediaItem.actors), joinedload(MediaItem.favorite))
        .filter(MediaItem.id == media_id)
        .one_or_none()
    )
    if not item:
        raise HTTPException(404, "media not found")
    fav = db.query(Favorite).filter(Favorite.media_id == media_id).one_or_none()
    if fav:
        db.delete(fav)
        db.commit()
        item = (
            db.query(MediaItem)
            .options(joinedload(MediaItem.actors), joinedload(MediaItem.favorite))
            .filter(MediaItem.id == media_id)
            .one()
        )
    return _with_proxied_images(item, detail=True, favorited=False)  # type: ignore[return-value]


@router.put("/{media_id}/rename", response_model=MediaDetail)
def rename_media(
    media_id: int,
    body: RenameIn,
    _: Annotated[dict, Depends(require_auth)],
    db: Session = Depends(get_db),
) -> MediaDetail:
    """Rename a media file on disk and update DB path/filename."""
    item = (
        db.query(MediaItem)
        .options(joinedload(MediaItem.actors), joinedload(MediaItem.favorite))
        .filter(MediaItem.id == media_id)
        .one_or_none()
    )
    if not item:
        raise HTTPException(404, "media not found")

    result = rename_media_item(db, item.library_id, media_id, body.new_filename)
    if not result.get("ok"):
        raise HTTPException(400, result.get("message", "rename failed"))

    # Refresh and return
    item = (
        db.query(MediaItem)
        .options(joinedload(MediaItem.actors), joinedload(MediaItem.favorite))
        .filter(MediaItem.id == media_id)
        .one()
    )
    return _with_proxied_images(item, detail=True)  # type: ignore[return-value]
