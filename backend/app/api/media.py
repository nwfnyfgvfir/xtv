from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.deps import require_auth
from app.models import Favorite, MediaItem
from app.schemas import MediaDetail, MediaListItem, PaginatedMedia, RescrapeIn
from app.services.images import site_proxy_url
from app.services.scrape import scrape_media_item

router = APIRouter()


def _with_proxied_images(
    item: MediaItem,
    *,
    detail: bool = False,
    favorited: bool | None = None,
) -> MediaListItem | MediaDetail:
    model = MediaDetail if detail else MediaListItem
    data = model.model_validate(item)
    data.cover_url = site_proxy_url(data.cover_url)
    data.thumb_url = site_proxy_url(data.thumb_url)
    if detail and isinstance(data, MediaDetail):
        data.backdrop_url = site_proxy_url(data.backdrop_url)
        data.actors = [
            a.model_copy(update={"image_url": site_proxy_url(a.image_url)}) for a in data.actors
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

    total = query.with_entities(func.count(MediaItem.id)).scalar() or 0
    items = (
        query.options(joinedload(MediaItem.favorite))
        .order_by(MediaItem.id.desc())
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
    if not item.number:
        raise HTTPException(400, "no number parsed; cannot scrape")
    body = body or RescrapeIn()
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
