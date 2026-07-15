from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from app.db import SessionLocal
from app.models import Library, MediaItem
from app.services.jobs import job_store
from app.services.scanner import run_rescrape_pending_job


def _seed_library():
    db = SessionLocal()
    try:
        lib = Library(name="t", path="local", type="mixed", enabled=True)
        db.add(lib)
        db.commit()
        db.refresh(lib)
        return lib.id
    finally:
        db.close()


def _add_item(library_id: int, *, number: str | None, scraped: bool) -> int:
    db = SessionLocal()
    try:
        item = MediaItem(
            library_id=library_id,
            path=f"/tmp/{number or 'nonum'}-{library_id}-{datetime.now().timestamp()}",
            filename=f"{number or 'x'}.mp4",
            number=number,
            title=number or "x",
            source_type="local",
            scraped_at=datetime.now(timezone.utc) if scraped else None,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item.id
    finally:
        db.close()


def test_rescrape_pending_only_unscraped_with_number():
    lib_id = _seed_library()
    pending_id = _add_item(lib_id, number="SSIS-001", scraped=False)
    _add_item(lib_id, number="SSIS-002", scraped=True)
    _add_item(lib_id, number=None, scraped=False)

    job = job_store.create(lib_id)
    called_ids: list[int] = []

    async def fake_scrape(db, item, force=False, provider_override=None, fallback_override=None):
        called_ids.append(item.id)
        item.scraped_at = datetime.now(timezone.utc)
        db.add(item)
        db.commit()
        return True

    with patch("app.services.scanner.scrape_media_item", new=AsyncMock(side_effect=fake_scrape)):
        run_rescrape_pending_job(job.job_id, lib_id)

    assert job.status == "done"
    assert job.scanned == 1
    assert job.scraped == 1
    assert called_ids == [pending_id]
    assert "scraped=1/1" in (job.message or "")


def test_rescrape_pending_empty():
    lib_id = _seed_library()
    _add_item(lib_id, number="SSIS-003", scraped=True)
    job = job_store.create(lib_id)
    with patch("app.services.scanner.scrape_media_item", new=AsyncMock()) as mock_scrape:
        run_rescrape_pending_job(job.job_id, lib_id)
        mock_scrape.assert_not_called()
    assert job.status == "done"
    assert job.scanned == 0
    assert "no pending" in (job.message or "")


def test_rescrape_pending_missing_library():
    job = job_store.create(999999)
    run_rescrape_pending_job(job.job_id, 999999)
    assert job.status == "error"
    assert "not found" in (job.message or "").lower()
