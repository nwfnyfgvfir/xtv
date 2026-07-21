from __future__ import annotations

from pathlib import Path

from app.db import SessionLocal, init_db
from app.models import Library, MediaItem
from app.services.duplicates import list_duplicate_groups
from app.services.media_delete import delete_media_item


def _cleanup_libs(db) -> None:
    for lib in db.query(Library).all():
        db.delete(lib)
    db.commit()


def _seed_lib(db, *, name: str = "t", path: str = "local") -> Library:
    lib = Library(name=name, path=path, type="local", enabled=True, auto_scan_enabled=False)
    db.add(lib)
    db.flush()
    return lib


def _add_media(
    db,
    lib: Library,
    *,
    number: str | None,
    filename: str,
    path: str | None = None,
    disc: str | None = None,
    subtitle_flag: str | None = None,
    source_type: str = "local",
    file_size: int | None = None,
) -> MediaItem:
    item = MediaItem(
        library_id=lib.id,
        path=path or f"/tmp/{lib.id}/{filename}",
        filename=filename,
        number=number,
        disc=disc,
        subtitle_flag=subtitle_flag,
        source_type=source_type,
        file_size=file_size,
    )
    db.add(item)
    db.flush()
    return item


def test_duplicates_group_by_number_case_insensitive() -> None:
    init_db()
    db = SessionLocal()
    try:
        lib_a = _seed_lib(db, name="A", path="a")
        lib_b = _seed_lib(db, name="B", path="b")
        _add_media(db, lib_a, number="SSIS-001", filename="SSIS-001.mp4")
        _add_media(db, lib_b, number="ssis-001", filename="ssis-001.mp4")
        _add_media(db, lib_a, number="SSIS-001", filename="SSIS-001-C.mp4", subtitle_flag="C")
        _add_media(db, lib_a, number="SSIS-001", filename="SSIS-001-cd1.mp4", disc="cd1")
        _add_media(db, lib_a, number="SSIS-001", filename="SSIS-001-cd2.mp4", disc="cd2")
        # Alone — not a duplicate group
        _add_media(db, lib_a, number="ABC-123", filename="ABC-123.mp4")
        # No number — ignored
        _add_media(db, lib_a, number=None, filename="random.mp4")
        db.commit()

        result = list_duplicate_groups(db, page=1, page_size=20)
        assert result.total == 1
        assert len(result.items) == 1
        group = result.items[0]
        assert group.number == "SSIS-001"
        assert group.count == 5
        assert len(group.items) == 5
        assert {i.library_name for i in group.items} == {"A", "B"}
        discs = {i.disc for i in group.items}
        assert "cd1" in discs and "cd2" in discs
        assert any(i.subtitle_flag == "C" for i in group.items)
    finally:
        _cleanup_libs(db)
        db.close()


def test_duplicates_pagination_and_query() -> None:
    init_db()
    db = SessionLocal()
    try:
        lib = _seed_lib(db)
        for n in ("AAA-001", "BBB-002", "CCC-003"):
            _add_media(db, lib, number=n, filename=f"{n}-a.mp4")
            _add_media(db, lib, number=n, filename=f"{n}-b.mp4")
        db.commit()

        all_g = list_duplicate_groups(db, page=1, page_size=2)
        assert all_g.total == 3
        assert len(all_g.items) == 2

        page2 = list_duplicate_groups(db, page=2, page_size=2)
        assert page2.total == 3
        assert len(page2.items) == 1

        filtered = list_duplicate_groups(db, page=1, page_size=20, q="bbb")
        assert filtered.total == 1
        assert filtered.items[0].number == "BBB-002"
    finally:
        _cleanup_libs(db)
        db.close()


def test_delete_media_item_strm_index_only(tmp_path: Path, monkeypatch) -> None:
    init_db()
    media_root = tmp_path / "media"
    lib_dir = media_root / "strm"
    lib_dir.mkdir(parents=True)

    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("MEDIA_ROOT", str(media_root))
    get_settings.cache_clear()

    strm = lib_dir / "X.strm"
    strm.write_text("https://example.com/x.mp4", encoding="utf-8")

    db = SessionLocal()
    try:
        lib = _seed_lib(db, path="strm")
        item = MediaItem(
            library_id=lib.id,
            path=str(strm.resolve()),
            filename=strm.name,
            number="X-001",
            source_type="strm",
            strm_target="https://example.com/x.mp4",
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        item_id = item.id

        delete_media_item(db, item)
        assert db.get(MediaItem, item_id) is None
        assert strm.exists()  # file kept
    finally:
        _cleanup_libs(db)
        db.close()
        get_settings.cache_clear()


def test_batch_delete_api_mixed(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    init_db()
    media_root = tmp_path / "media"
    lib_dir = media_root / "local"
    lib_dir.mkdir(parents=True)

    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("MEDIA_ROOT", str(media_root))
    get_settings.cache_clear()

    video = lib_dir / "KEEP-001.mp4"
    video.write_bytes(b"video")

    db = SessionLocal()
    try:
        lib = _seed_lib(db, path="local")
        local = MediaItem(
            library_id=lib.id,
            path=str(video.resolve()),
            filename=video.name,
            number="KEEP-001",
            source_type="local",
        )
        strm_item = MediaItem(
            library_id=lib.id,
            path=str((lib_dir / "KEEP-001.strm").resolve()),
            filename="KEEP-001.strm",
            number="KEEP-001",
            source_type="strm",
            strm_target="https://example.com/k.mp4",
        )
        db.add_all([local, strm_item])
        db.commit()
        db.refresh(local)
        db.refresh(strm_item)
        local_id, strm_id = local.id, strm_item.id
    finally:
        db.close()

    client = TestClient(app)
    r = client.post(
        "/api/media/batch-delete",
        json={"ids": [local_id, strm_id, 999999]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["deleted"]) == {local_id, strm_id}
    assert any(f["id"] == 999999 for f in body["failed"])
    assert not video.exists()

    db = SessionLocal()
    try:
        assert db.get(MediaItem, local_id) is None
        assert db.get(MediaItem, strm_id) is None
    finally:
        _cleanup_libs(db)
        db.close()
        get_settings.cache_clear()


def test_list_duplicates_api() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    init_db()
    db = SessionLocal()
    try:
        lib = _seed_lib(db)
        _add_media(db, lib, number="DUP-9", filename="a.mp4")
        _add_media(db, lib, number="DUP-9", filename="b.mp4")
        db.commit()
    finally:
        db.close()

    client = TestClient(app)
    r = client.get("/api/media/duplicates")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total"] >= 1
    numbers = [g["number"] for g in data["items"]]
    assert "DUP-9" in numbers

    db = SessionLocal()
    try:
        _cleanup_libs(db)
    finally:
        db.close()
