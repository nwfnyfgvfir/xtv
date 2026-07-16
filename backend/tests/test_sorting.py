from app.models import Actor
from app.services.sorting import (
    DEFAULT_ACTOR_SORT,
    DEFAULT_SORT,
    actor_order_by,
    media_order_by,
    normalize_actor_sort,
    normalize_sort,
)


def test_normalize_sort():
    assert normalize_sort(None) == DEFAULT_SORT
    assert normalize_sort("bogus") == DEFAULT_SORT
    assert normalize_sort("number_asc") == "number_asc"
    assert normalize_sort("RELEASE_DESC") == "release_desc"


def test_media_order_by_returns_clauses():
    for key in (
        "number_asc",
        "number_desc",
        "created_asc",
        "created_desc",
        "release_asc",
        "release_desc",
    ):
        clauses = media_order_by(key)
        assert isinstance(clauses, list)
        assert len(clauses) >= 2


def test_normalize_actor_sort():
    assert normalize_actor_sort(None) == DEFAULT_ACTOR_SORT
    assert normalize_actor_sort("bogus") == DEFAULT_ACTOR_SORT
    assert normalize_actor_sort("debut_asc") == "debut_asc"
    assert normalize_actor_sort("DEBUT_DESC") == "debut_desc"
    assert normalize_actor_sort("media_count_desc") == "media_count_desc"


def test_actor_order_by_returns_clauses():
    # Columns can be any SQLAlchemy expression; use Actor columns as stand-ins.
    for key in ("media_count_desc", "debut_asc", "debut_desc"):
        clauses = actor_order_by(key, Actor.id, Actor.name)
        assert isinstance(clauses, list)
        assert len(clauses) >= 2
