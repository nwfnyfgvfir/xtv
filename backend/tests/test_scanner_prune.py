from __future__ import annotations

from pathlib import Path

from app.db import SessionLocal, init_db
from app.models import Library, MediaItem
from app.services.jobs import ScanJob
from app.services.scanner import scan_library_sync


def test_scan_prunes_missing_and_adds_new(tmp_path: Path, monkeypatch) -> None:
    init_db()
    media_root = tmp_path / "media"
    lib_dir = media_root / "local"
    lib_dir.mkdir(parents=True)

    # Point settings media root at temp dir
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("MEDIA_ROOT", str(media_root))
    # Keep scan unit test offline (no MetaTube / translate side effects).
    monkeypatch.setenv("AUTO_SCRAPE", "false")
    monkeypatch.setenv("AUTO_TRANSLATE", "false")
    get_settings.cache_clear()

    keep = lib_dir / "KEEP-001.mp4"
    gone = lib_dir / "GONE-002.mp4"
    keep.write_bytes(b"x")
    gone.write_bytes(b"y")

    db = SessionLocal()
    try:
        lib = Library(name="t", path="local", type="local", enabled=True, auto_scan_enabled=False)
        db.add(lib)
        db.commit()
        db.refresh(lib)

        job1 = ScanJob(job_id="j1", library_id=lib.id)
        scan_library_sync(db, lib, job1)
        assert job1.status == "done"
        assert job1.created == 2
        assert job1.removed == 0
        assert db.query(MediaItem).filter(MediaItem.library_id == lib.id).count() == 2

        gone.unlink()
        new = lib_dir / "NEW-003.mp4"
        new.write_bytes(b"z")

        job2 = ScanJob(job_id="j2", library_id=lib.id)
        scan_library_sync(db, lib, job2)
        assert job2.status == "done"
        assert job2.removed == 1
        assert job2.created == 1
        paths = {m.filename for m in db.query(MediaItem).filter(MediaItem.library_id == lib.id).all()}
        assert paths == {"KEEP-001.mp4", "NEW-003.mp4"}
    finally:
        # cleanup library rows
        for lib in db.query(Library).all():
            db.delete(lib)
        db.commit()
        db.close()
        get_settings.cache_clear()
