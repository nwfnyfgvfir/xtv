from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.deps import require_auth
from app.models import Actor, ActorFavorite, MediaActor, MediaItem
from app.schemas import ActorDetail, ActorListItem, MediaListItem, PaginatedActors, PaginatedMedia
from app.services.images import rewrite_image_url
from app.services.scrape import enrich_actor_image
from app.services.sorting import actor_order_by, media_order_by

router = APIRouter(prefix="/actors", tags=["actors"])


def _proxy_media(item: MediaItem, favorited_ids: set[int]) -> MediaListItem:
    data = MediaListItem.model_validate(item)
    data.cover_url = rewrite_image_url(
        data.cover_url, provider=item.provider, provider_id=item.provider_id
    )
    data.thumb_url = rewrite_image_url(
        data.thumb_url, provider=item.provider, provider_id=item.provider_id
    )
    data.favorited = item.id in favorited_ids
    return data


def _actor_item(actor: Actor, media_count: int = 0, favorited: bool = False) -> ActorListItem:
    return ActorListItem(
        id=actor.id,
        name=actor.name,
        provider=actor.provider,
        provider_id=actor.provider_id,
        # Actor portraits use site proxy (MetaTube primary is movie-oriented).
        image_url=rewrite_image_url(actor.image_url),
        media_count=media_count,
        favorited=favorited,
    )


def _media_count(db: Session, actor_id: int) -> int:
    return db.query(func.count(MediaActor.media_id)).filter(MediaActor.actor_id == actor_id).scalar() or 0


def _is_favorited(db: Session, actor_id: int) -> bool:
    return (
        db.query(ActorFavorite.id).filter(ActorFavorite.actor_id == actor_id).one_or_none() is not None
    )


def _actor_detail(db: Session, actor: Actor, favorited: bool | None = None) -> ActorDetail:
    cnt = _media_count(db, actor.id)
    fav = favorited if favorited is not None else _is_favorited(db, actor.id)
    base = _actor_item(actor, int(cnt), favorited=fav)
    return ActorDetail(**base.model_dump())


@router.get("", response_model=PaginatedActors)
def list_actors(
    _: Annotated[dict, Depends(require_auth)],
    q: str | None = None,
    sort: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(48, ge=1, le=200),
    db: Session = Depends(get_db),
) -> PaginatedActors:
    count_sub = (
        db.query(MediaActor.actor_id, func.count(MediaActor.media_id).label("cnt"))
        .group_by(MediaActor.actor_id)
        .subquery()
    )
    # Library first-work date as proxy for 出道日期.
    debut_sub = (
        db.query(
            MediaActor.actor_id,
            func.min(MediaItem.release_date).label("debut_date"),
        )
        .join(MediaItem, MediaItem.id == MediaActor.media_id)
        .filter(MediaItem.release_date.isnot(None), MediaItem.release_date != "")
        .group_by(MediaActor.actor_id)
        .subquery()
    )
    media_count_col = func.coalesce(count_sub.c.cnt, 0)
    debut_col = debut_sub.c.debut_date
    query = (
        db.query(Actor, media_count_col.label("media_count"))
        .outerjoin(count_sub, Actor.id == count_sub.c.actor_id)
        .outerjoin(debut_sub, Actor.id == debut_sub.c.actor_id)
    )
    if q:
        query = query.filter(Actor.name.ilike(f"%{q}%"))
    total = query.count()
    rows = (
        query.order_by(*actor_order_by(sort, media_count_col, debut_col))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    actor_ids = [actor.id for actor, _ in rows]
    fav_ids: set[int] = set()
    if actor_ids:
        fav_ids = {
            aid
            for (aid,) in db.query(ActorFavorite.actor_id)
            .filter(ActorFavorite.actor_id.in_(actor_ids))
            .all()
        }
    items = [
        _actor_item(actor, int(cnt or 0), favorited=actor.id in fav_ids) for actor, cnt in rows
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
    return _actor_detail(db, actor)


@router.post("/{actor_id}/favorite", response_model=ActorDetail)
def favorite_actor(
    actor_id: int,
    _: Annotated[dict, Depends(require_auth)],
    db: Session = Depends(get_db),
) -> ActorDetail:
    actor = db.get(Actor, actor_id)
    if not actor:
        raise HTTPException(404, "actor not found")
    existing = db.query(ActorFavorite).filter(ActorFavorite.actor_id == actor_id).one_or_none()
    if existing is None:
        db.add(ActorFavorite(actor_id=actor_id))
        db.commit()
        db.refresh(actor)
    return _actor_detail(db, actor, favorited=True)


@router.delete("/{actor_id}/favorite", response_model=ActorDetail)
def unfavorite_actor(
    actor_id: int,
    _: Annotated[dict, Depends(require_auth)],
    db: Session = Depends(get_db),
) -> ActorDetail:
    actor = db.get(Actor, actor_id)
    if not actor:
        raise HTTPException(404, "actor not found")
    fav = db.query(ActorFavorite).filter(ActorFavorite.actor_id == actor_id).one_or_none()
    if fav:
        db.delete(fav)
        db.commit()
        db.refresh(actor)
    return _actor_detail(db, actor, favorited=False)


@router.post("/{actor_id}/rescrape-image", response_model=ActorDetail)
async def rescrape_actor_image(
    actor_id: int,
    _: Annotated[dict, Depends(require_auth)],
    db: Session = Depends(get_db),
) -> ActorDetail:
    actor = db.get(Actor, actor_id)
    if not actor:
        raise HTTPException(404, "actor not found")
    # force re-fetch
    actor.image_url = None
    db.add(actor)
    db.commit()
    ok = await enrich_actor_image(db, actor)
    db.refresh(actor)
    if not ok and not actor.image_url:
        raise HTTPException(502, "actor image not found")
    return _actor_detail(db, actor)


@router.get("/{actor_id}/media", response_model=PaginatedMedia)
def actor_media(
    actor_id: int,
    _: Annotated[dict, Depends(require_auth)],
    sort: str | None = Query(None),
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
        .order_by(*media_order_by(sort))
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
