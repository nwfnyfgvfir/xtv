from __future__ import annotations

import logging
from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Actor, ActorFavorite, MediaActor

logger = logging.getLogger(__name__)


def normalize_actor_name(name: str | None) -> str:
    return (name or "").strip()


def pick_canonical(actors: list[Actor]) -> Actor:
    """Prefer provider key, then image, then lowest id."""

    def rank(a: Actor) -> tuple[int, int, int]:
        has_provider = 1 if (a.provider and a.provider_id) else 0
        has_image = 1 if a.image_url else 0
        return (has_provider, has_image, -int(a.id or 0))

    return max(actors, key=rank)


def merge_actors(db: Session, keep: Actor, drop: Actor) -> Actor:
    """Merge drop into keep: move media links, fill missing fields, delete drop."""
    if keep.id is None or drop.id is None or keep.id == drop.id:
        return keep

    keep_id = keep.id
    drop_id = drop.id

    # Composite PK (media_id, actor_id) — do not UPDATE actor_id in place.
    drop_media_ids = [
        mid
        for (mid,) in db.query(MediaActor.media_id).filter(MediaActor.actor_id == drop_id).all()
    ]
    keep_media_ids = {
        mid
        for (mid,) in db.query(MediaActor.media_id).filter(MediaActor.actor_id == keep_id).all()
    }
    db.query(MediaActor).filter(MediaActor.actor_id == drop_id).delete(synchronize_session=False)
    for media_id in drop_media_ids:
        if media_id not in keep_media_ids:
            db.add(MediaActor(media_id=media_id, actor_id=keep_id))
            keep_media_ids.add(media_id)

    drop_image = drop.image_url
    drop_provider = drop.provider
    drop_provider_id = drop.provider_id
    drop_name = drop.name

    # Free unique (provider, provider_id) before reassigning to keep.
    if drop_provider or drop_provider_id:
        drop.provider = None
        drop.provider_id = None
        db.add(drop)
        db.flush()

    # Preserve favorites: drop → keep (at most one row on keep).
    keep_fav = (
        db.query(ActorFavorite).filter(ActorFavorite.actor_id == keep_id).one_or_none()
    )
    drop_fav = (
        db.query(ActorFavorite).filter(ActorFavorite.actor_id == drop_id).one_or_none()
    )
    if drop_fav is not None:
        drop_created = drop_fav.created_at
        db.delete(drop_fav)
        db.flush()
        if keep_fav is None:
            db.add(ActorFavorite(actor_id=keep_id, created_at=drop_created))
        elif drop_created is not None and (
            keep_fav.created_at is None or drop_created < keep_fav.created_at
        ):
            keep_fav.created_at = drop_created
            db.add(keep_fav)

    if not keep.image_url and drop_image:
        keep.image_url = drop_image

    # Fill provider keys only when keep lacks them and the key is free.
    if (not keep.provider or not keep.provider_id) and drop_provider and drop_provider_id:
        existing = (
            db.query(Actor)
            .filter(Actor.provider == drop_provider, Actor.provider_id == drop_provider_id)
            .one_or_none()
        )
        if existing is None or existing.id == keep_id:
            if not keep.provider:
                keep.provider = drop_provider
            if not keep.provider_id:
                keep.provider_id = drop_provider_id

    if not keep.name and drop_name:
        keep.name = drop_name

    db.add(keep)
    db.delete(drop)
    db.flush()
    return keep


def delete_orphan_actors(db: Session) -> int:
    """Delete actors with zero media_actors links. Returns deleted count."""
    orphans = (
        db.query(Actor)
        .outerjoin(MediaActor, MediaActor.actor_id == Actor.id)
        .filter(MediaActor.actor_id.is_(None))
        .all()
    )
    n = 0
    for actor in orphans:
        db.delete(actor)
        n += 1
    if n:
        db.flush()
    return n


def dedupe_actors(db: Session) -> int:
    """Merge exact-name duplicates (trimmed) and resolve provider-key collisions.

    Returns number of actors dropped via merge.
    """
    dropped = 0

    # 1) Exact trimmed-name groups
    name_rows = (
        db.query(func.trim(Actor.name).label("n"), func.count(Actor.id))
        .filter(Actor.name.isnot(None), func.trim(Actor.name) != "")
        .group_by(func.trim(Actor.name))
        .having(func.count(Actor.id) > 1)
        .all()
    )
    for trimmed, _cnt in name_rows:
        matches = (
            db.query(Actor)
            .filter(func.trim(Actor.name) == trimmed)
            .order_by(Actor.id.asc())
            .all()
        )
        if len(matches) < 2:
            continue
        keep = pick_canonical(matches)
        keep.name = normalize_actor_name(keep.name) or keep.name
        for other in matches:
            if other.id == keep.id:
                continue
            # other may already be deleted if a previous merge cascade-touched it
            if db.get(Actor, other.id) is None:
                continue
            merge_actors(db, keep=keep, drop=other)
            dropped += 1

    # 2) Provider-key groups (defensive; unique constraint should prevent >1)
    #    Group in Python for SQLite null-safety.
    keyed: dict[tuple[str, str], list[Actor]] = defaultdict(list)
    for actor in db.query(Actor).filter(Actor.provider.isnot(None), Actor.provider_id.isnot(None)).all():
        keyed[(str(actor.provider), str(actor.provider_id))].append(actor)
    for _key, group in keyed.items():
        if len(group) < 2:
            continue
        keep = pick_canonical(group)
        for other in group:
            if other.id == keep.id:
                continue
            if db.get(Actor, other.id) is None:
                continue
            merge_actors(db, keep=keep, drop=other)
            dropped += 1

    if dropped:
        db.flush()
    return dropped
