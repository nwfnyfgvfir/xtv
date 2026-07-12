from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.deps import require_auth
from app.models import Actor, MediaActor, MediaItem
from app.schemas import ActorDetail, ActorListItem, MediaListItem, PaginatedActors, PaginatedMedia
from app.services.metatube import MetaTubeClient

router = APIRouter(prefix="/actors", tags=["actors"])


def _proxy_media(item: MediaItem, favorited_ids: set[int]) -> MediaListItem:
    client = MetaTubeClient()
    data = MediaListItem.model_validate(item)
    data.cover_url = client.proxied_image_url(item.provider, item.provider_id, data.cover_url)
    data.thumb_url = client.proxied_image_url(item.provider, item.provider_id, data.thumb_url)
    data.favorited = item.id in favorited_ids
    return data


@router.get("", response_model=PaginatedActors)
def list_actors(
    _: Annotated[dict, Depends(require_auth)],
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(48, ge=1, le=200),
    db: Session = Depends(get_db),
) -> PaginatedActors:
    count_sub = (
        db.query(MediaActor.actor_id, func.count(MediaActor.media_id).label("cnt"))
        .group_by(MediaActor.actor_id)
        .subquery()
    )
    query = db.query(Actor, func.coalesce(count_sub.c.cnt, 0).label("media_count")).outerjoin(
        count_sub, Actor.id == count_sub.c.actor_id
    )
    if q:
        query = query.filter(Actor.name.ilike(f"%{q}%"))
    total = query.count()
    rows = (
        query.order_by(func.coalesce(count_sub.c.cnt, 0).desc(), Actor.name.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [
        ActorListItem(
            id=actor.id,
            name=actor.name,
            provider=actor.provider,
            provider_id=actor.provider_id,
            image_url=actor.image_url,
            media_count=int(cnt or 0),
        )
        for actor, cnt in rows
    ]
    return PaginatedActors(items=items, total=total, page=page, page_size=page_size)


@router.get("/{actor_id}", response_model=ActorDetail)
def get_actor(
    actor_id: int,
    _: Annotated[dict, Depends(require_auth)],
    db: Session = Depends(get_db),
) -> ActorDetail:
    actor = db.get(Actor, actor_id)
    if not actor:
        raise HTTPException(404, "actor not found")
    cnt = db.query(func.count(MediaActor.media_id)).filter(MediaActor.actor_id == actor_id).scalar() or 0
    return ActorDetail(
        id=actor.id,
        name=actor.name,
        provider=actor.provider,
        provider_id=actor.provider_id,
        image_url=actor.image_url,
        media_count=int(cnt),
    )


@router.get("/{actor_id}/media", response_model=PaginatedMedia)
def actor_media(
    actor_id: int,
    _: Annotated[dict, Depends(require_auth)],
    page: int = Query(1, ge=1),
    page_size: int = Query(48, ge=1, le=200),
    db: Session = Depends(get_db),
) -> PaginatedMedia:
    actor = db.get(Actor, actor_id)
    if not actor:
        raise HTTPException(404, "actor not found")
    query = (
        db.query(MediaItem)
        .join(MediaActor, MediaActor.media_id == MediaItem.id)
        .filter(MediaActor.actor_id == actor_id)
    )
    total = query.with_entities(func.count(MediaItem.id)).scalar() or 0
    items = (
        query.options(joinedload(MediaItem.favorite))
        .order_by(MediaItem.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    fav_ids = {i.id for i in items if i.favorite is not None}
    return PaginatedMedia(
        items=[_proxy_media(i, fav_ids) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )
