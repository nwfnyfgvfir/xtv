from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.deps import require_auth
from app.models import Actor, ActorFavorite, Favorite, MediaActor, MediaItem
from app.schemas import ActorListItem, MediaListItem, PaginatedActors, PaginatedMedia
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


def _to_actor_item(actor: Actor, media_count: int) -> ActorListItem:
    return ActorListItem(
        id=actor.id,
        name=actor.name,
        provider=actor.provider,
        provider_id=actor.provider_id,
        image_url=rewrite_image_url(actor.image_url),
        media_count=media_count,
        favorited=True,
    )


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


@router.get("/actors", response_model=PaginatedActors)
def list_favorite_actors(
    _: Annotated[dict, Depends(require_auth)],
    page: int = Query(1, ge=1),
    page_size: int = Query(48, ge=1, le=200),
    db: Session = Depends(get_db),
) -> PaginatedActors:
    count_sub = (
        db.query(MediaActor.actor_id, func.count(MediaActor.media_id).label("cnt"))
        .group_by(MediaActor.actor_id)
        .subquery()
    )
    query = (
        db.query(Actor, func.coalesce(count_sub.c.cnt, 0).label("media_count"))
        .join(ActorFavorite, ActorFavorite.actor_id == Actor.id)
        .outerjoin(count_sub, Actor.id == count_sub.c.actor_id)
    )
    total = query.count()
    rows = (
        query.order_by(ActorFavorite.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedActors(
        items=[_to_actor_item(actor, int(cnt or 0)) for actor, cnt in rows],
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
