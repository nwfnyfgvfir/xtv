from __future__ import annotations

from pathlib import Path

from app.db import SessionLocal, init_db
from app.models import Library, MediaItem
from app.services.library_revision import get_revision
from app.services.scanner import ingest_path, refresh_paths, remove_path


def test_path_ingest_remove_and_revision(tmp_path: Path, monkeypatch) -> None:
    init_db()
    media_root = tmp_path / "media"
    lib_dir = media_root / "local"
    lib_dir.mkdir(parents=True)

    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("MEDIA_ROOT", str(media_root))
    monkeypatch.setenv("AUTO_SCRAPE", "false")
    get_settings.cache_clear()

    db = SessionLocal()
    try:
        lib = Library(name="t", path="local", type="local", enabled=True, auto_scan_enabled=False)
        db.add(lib)
        db.commit()
        db.refresh(lib)
        lib_id = lib.id
        rev0 = get_revision(lib_id)

        f = lib_dir / "ABC-001.mp4"
        f.write_bytes(b"x")
        r = ingest_path(lib_id, f)
        assert r["ok"] is True
        assert r["created"] == 1
        assert get_revision(lib_id) > rev0
        assert db.query(MediaItem).filter(MediaItem.library_id == lib_id).count() == 1

        f.unlink()
        r2 = remove_path(lib_id, f)
        assert r2["ok"] is True
        assert r2["removed"] == 1
        assert db.query(MediaItem).filter(MediaItem.library_id == lib_id).count() == 0

        # refresh_paths: add + remove in one batch
        a = lib_dir / "A-1.mp4"
        b = lib_dir / "B-2.mp4"
        a.write_bytes(b"a")
        b.write_bytes(b"b")
        summary = refresh_paths(lib_id, [str(a), str(b)])
        assert summary["ok"] is True
        assert summary["created"] == 2
        assert db.query(MediaItem).filter(MediaItem.library_id == lib_id).count() == 2

        b.unlink()
        summary2 = refresh_paths(lib_id, [str(b)])
        assert summary2["removed"] == 1
        paths = {m.filename for m in db.query(MediaItem).filter(MediaItem.library_id == lib_id).all()}
        assert paths == {"A-1.mp4"}
    finally:
        for lib in db.query(Library).all():
            db.delete(lib)
        db.commit()
        db.close()
        get_settings.cache_clear()
