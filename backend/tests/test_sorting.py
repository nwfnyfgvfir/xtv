from app.services.sorting import DEFAULT_SORT, media_order_by, normalize_sort


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
