from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.models import MediaItem
from app.schemas import MediaDetail, MediaListItem, PaginatedMedia
from app.services.metatube import MetaTubeClient
from app.services.scrape import scrape_media_item

router = APIRouter()


def _with_proxied_images(item: MediaItem, *, detail: bool = False) -> MediaListItem | MediaDetail:
    """Serialize media and rewrite legacy source CDN URLs via MetaTube proxy."""
    model = MediaDetail if detail else MediaListItem
    data = model.model_validate(item)
    client = MetaTubeClient()
    provider = item.provider
    provider_id = item.provider_id
    data.cover_url = client.proxied_image_url(provider, provider_id, data.cover_url)
    data.thumb_url = client.proxied_image_url(provider, provider_id, data.thumb_url)
    if detail and isinstance(data, MediaDetail):
        data.backdrop_url = client.proxied_image_url(provider, provider_id, data.backdrop_url)
    return data


@router.get("", response_model=PaginatedMedia)
def list_media(
    q: str | None = None,
    library_id: int | None = None,
    scraped: bool | None = None,
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

    total = query.with_entities(func.count(MediaItem.id)).scalar() or 0
    items = (
        query.order_by(MediaItem.id.desc())
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
def get_media(media_id: int, db: Session = Depends(get_db)) -> MediaDetail:
    item = (
        db.query(MediaItem)
        .options(joinedload(MediaItem.actors))
        .filter(MediaItem.id == media_id)
        .one_or_none()
    )
    if not item:
        raise HTTPException(404, "media not found")
    return _with_proxied_images(item, detail=True)  # type: ignore[return-value]


@router.post("/{media_id}/rescrape", response_model=MediaDetail)
async def rescrape_media(media_id: int, db: Session = Depends(get_db)) -> MediaDetail:
    item = (
        db.query(MediaItem)
        .options(joinedload(MediaItem.actors))
        .filter(MediaItem.id == media_id)
        .one_or_none()
    )
    if not item:
        raise HTTPException(404, "media not found")
    if not item.number:
        raise HTTPException(400, "no number parsed; cannot scrape")
    ok = await scrape_media_item(db, item, force=True)
    db.refresh(item)
    if not ok and not item.scraped_at:
        raise HTTPException(502, "scrape failed or no results")
    # re-load actors
    item = (
        db.query(MediaItem)
        .options(joinedload(MediaItem.actors))
        .filter(MediaItem.id == media_id)
        .one()
    )
    return _with_proxied_images(item, detail=True)  # type: ignore[return-value]
