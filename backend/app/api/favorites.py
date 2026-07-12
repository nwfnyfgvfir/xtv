from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.deps import require_auth
from app.models import Favorite, MediaItem
from app.schemas import MediaListItem, PaginatedMedia
from app.services.images import rewrite_image_url
from app.services.sorting import media_order_by

router = APIRouter(prefix="/favorites", tags=["favorites"])


def _to_item(item: MediaItem) -> MediaListItem:
    data = MediaListItem.model_validate(item)
    data.cover_url = rewrite_image_url(
        data.cover_url, provider=item.provider, provider_id=item.provider_id
    )
    data.thumb_url = rewrite_image_url(
        data.thumb_url, provider=item.provider, provider_id=item.provider_id
    )
    data.favorited = True
    return data


@router.get("", response_model=PaginatedMedia)
def list_favorites(
    _: Annotated[dict, Depends(require_auth)],
    sort: str | None = Query(None, description="omit = favorite time desc; else media sort keys"),
    page: int = Query(1, ge=1),
    page_size: int = Query(48, ge=1, le=200),
    db: Session = Depends(get_db),
) -> PaginatedMedia:
    query = db.query(MediaItem).join(Favorite, Favorite.media_id == MediaItem.id)
    total = query.with_entities(func.count(MediaItem.id)).scalar() or 0
    order = media_order_by(sort) if sort else [Favorite.created_at.desc()]
    items = (
        query.options(joinedload(MediaItem.favorite))
        .order_by(*order)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedMedia(
        items=[_to_item(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/{media_id}", response_model=MediaListItem)
def add_favorite(
    media_id: int,
    _: Annotated[dict, Depends(require_auth)],
    db: Session = Depends(get_db),
) -> MediaListItem:
    item = db.get(MediaItem, media_id)
    if not item:
        raise HTTPException(404, "media not found")
    existing = db.query(Favorite).filter(Favorite.media_id == media_id).one_or_none()
    if existing is None:
        db.add(Favorite(media_id=media_id))
        db.commit()
    db.refresh(item)
    return _to_item(item)


@router.delete("/{media_id}", status_code=204)
def remove_favorite(
    media_id: int,
    _: Annotated[dict, Depends(require_auth)],
    db: Session = Depends(get_db),
) -> None:
    fav = db.query(Favorite).filter(Favorite.media_id == media_id).one_or_none()
    if fav:
        db.delete(fav)
        db.commit()
