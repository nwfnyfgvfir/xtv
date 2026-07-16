from __future__ import annotations

from typing import Any

from sqlalchemy import case

from app.models import Actor, MediaItem

DEFAULT_SORT = "created_desc"
VALID_SORTS = frozenset(
    {
        "number_asc",
        "number_desc",
        "created_asc",
        "created_desc",
        "release_asc",
        "release_desc",
    }
)

DEFAULT_ACTOR_SORT = "media_count_desc"
VALID_ACTOR_SORTS = frozenset(
    {
        "media_count_desc",
        "debut_asc",
        "debut_desc",
    }
)


def normalize_sort(sort: str | None) -> str:
    s = (sort or DEFAULT_SORT).strip().lower()
    return s if s in VALID_SORTS else DEFAULT_SORT


def normalize_actor_sort(sort: str | None) -> str:
    s = (sort or DEFAULT_ACTOR_SORT).strip().lower()
    return s if s in VALID_ACTOR_SORTS else DEFAULT_ACTOR_SORT


def _nulls_last_key(col: Any):
    """SQLite-friendly nulls-last: null/empty sort after real values."""
    return case((col.is_(None), 1), (col == "", 1), else_=0)


def media_order_by(sort: str | None) -> list[Any]:
    """Return SQLAlchemy ORDER BY clauses for media list endpoints."""
    key = normalize_sort(sort)
    if key == "number_asc":
        return [_nulls_last_key(MediaItem.number), MediaItem.number.asc(), MediaItem.id.asc()]
    if key == "number_desc":
        return [_nulls_last_key(MediaItem.number), MediaItem.number.desc(), MediaItem.id.desc()]
    if key == "created_asc":
        return [MediaItem.created_at.asc(), MediaItem.id.asc()]
    if key == "release_asc":
        return [
            _nulls_last_key(MediaItem.release_date),
            MediaItem.release_date.asc(),
            MediaItem.id.asc(),
        ]
    if key == "release_desc":
        return [
            _nulls_last_key(MediaItem.release_date),
            MediaItem.release_date.desc(),
            MediaItem.id.desc(),
        ]
    # created_desc (default)
    return [MediaItem.created_at.desc(), MediaItem.id.desc()]


def actor_order_by(
    sort: str | None,
    media_count_col: Any,
    debut_col: Any,
) -> list[Any]:
    """Return ORDER BY clauses for actor list endpoints.

    `debut_col` is typically MIN(MediaItem.release_date) per actor (library first work).
    """
    key = normalize_actor_sort(sort)
    if key == "debut_asc":
        return [
            _nulls_last_key(debut_col),
            debut_col.asc(),
            Actor.name.asc(),
            Actor.id.asc(),
        ]
    if key == "debut_desc":
        return [
            _nulls_last_key(debut_col),
            debut_col.desc(),
            Actor.name.asc(),
            Actor.id.asc(),
        ]
    # media_count_desc (default)
    return [media_count_col.desc(), Actor.name.asc(), Actor.id.asc()]
