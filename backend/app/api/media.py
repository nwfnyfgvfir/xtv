from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.deps import require_auth
from app.models import Favorite, MediaItem
from app.schemas import MediaDetail, MediaListItem, PaginatedMedia, RescrapeIn
from app.services.images import rewrite_image_url
from app.services.media_delete import delete_local_media
from app.services.naming import normalize_number
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


@router.post("/{media_id}/rescrape", response_model=MediaDetail)
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
    body = body or RescrapeIn()
    if body.number is not None and str(body.number).strip():
        normalized = normalize_number(body.number)
        if not normalized:
            raise HTTPException(400, "invalid number")
        item.number = normalized
        db.add(item)
        db.commit()
        db.refresh(item)
    if not item.number:
        raise HTTPException(400, "no number; provide number to scrape")
    ok = await scrape_media_item(
        db,
        item,
        force=True,
        provider_override=body.provider,
        fallback_override=body.fallback,
    )
    db.refresh(item)
    if not ok and not item.scraped_at:
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
    """Delete a local media file from disk and remove its library index row."""
    item = db.get(MediaItem, media_id)
    if not item:
        raise HTTPException(404, "media not found")
    delete_local_media(db, item)


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
