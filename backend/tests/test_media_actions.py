from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.db import SessionLocal, init_db
from app.models import Library, MediaItem
from app.services.media_delete import delete_local_media, ensure_media_path_allowed
from app.services.scrape import apply_translations


def _cleanup_libs(db) -> None:
    for lib in db.query(Library).all():
        db.delete(lib)
    db.commit()


def _seed_lib(db, *, path: str = "local") -> Library:
    lib = Library(name="t", path=path, type="local", enabled=True, auto_scan_enabled=False)
    db.add(lib)
    db.flush()
    return lib


def test_apply_translations_from_originals(monkeypatch) -> None:
    init_db()
    db = SessionLocal()
    try:
        lib = _seed_lib(db)
        item = MediaItem(
            library_id=lib.id,
            path="/tmp/t1.mp4",
            filename="t1.mp4",
            number="TEST-001",
            title="旧译标题",
            title_original="原タイトルです",
            plot="旧译简介",
            plot_original="原あらすじです",
            tags_json=json.dumps(["痴女", "中文字幕"], ensure_ascii=False),
            source_type="local",
        )
        db.add(item)
        db.flush()

        # Manual re-translate: reset display to source then apply
        src_title = item.title_original or item.title
        src_plot = item.plot_original or item.plot
        tags = json.loads(item.tags_json or "[]")
        item.title = src_title
        item.plot = src_plot

        async def fake_translate(text: str) -> str:
            return f"ZH:{text}"

        async def fake_tags(tags_in: list[str]) -> list[str]:
            return [f"ZH:{t}" if t != "中文字幕" else t for t in tags_in]

        monkeypatch.setattr("app.services.translate.translate_text", fake_translate)
        monkeypatch.setattr("app.services.translate.translate_tags", fake_tags)

        asyncio.run(
            apply_translations(db, item, src_title=src_title, src_plot=src_plot, tags=tags)
        )
        db.commit()
        db.refresh(item)

        assert item.title_original == "原タイトルです"
        assert item.plot_original == "原あらすじです"
        assert item.title == "ZH:原タイトルです"
        assert item.plot == "ZH:原あらすじです"
        assert json.loads(item.tags_json) == ["ZH:痴女", "中文字幕"]
    finally:
        _cleanup_libs(db)
        db.close()


def test_delete_local_media_removes_file_and_sidecars(tmp_path: Path, monkeypatch) -> None:
    init_db()
    media_root = tmp_path / "media"
    lib_dir = media_root / "local"
    lib_dir.mkdir(parents=True)

    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("MEDIA_ROOT", str(media_root))
    get_settings.cache_clear()

    video = lib_dir / "KEEP-DEL-001.mp4"
    sub = lib_dir / "KEEP-DEL-001.zh.srt"
    video.write_bytes(b"video")
    sub.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")

    db = SessionLocal()
    try:
        lib = _seed_lib(db, path="local")
        item = MediaItem(
            library_id=lib.id,
            path=str(video.resolve()),
            filename=video.name,
            number="KEEP-DEL-001",
            source_type="local",
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        item_id = item.id

        delete_local_media(db, item)

        assert not video.exists()
        assert not sub.exists()
        assert db.get(MediaItem, item_id) is None
    finally:
        _cleanup_libs(db)
        db.close()
        get_settings.cache_clear()


def test_delete_local_media_missing_file_still_drops_db(tmp_path: Path, monkeypatch) -> None:
    init_db()
    media_root = tmp_path / "media"
    lib_dir = media_root / "local"
    lib_dir.mkdir(parents=True)

    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("MEDIA_ROOT", str(media_root))
    get_settings.cache_clear()

    video = lib_dir / "GONE-DEL-002.mp4"
    # do not create file

    db = SessionLocal()
    try:
        lib = _seed_lib(db, path="local")
        item = MediaItem(
            library_id=lib.id,
            path=str(video.resolve()),
            filename=video.name,
            number="GONE-DEL-002",
            source_type="local",
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        item_id = item.id

        delete_local_media(db, item)
        assert db.get(MediaItem, item_id) is None
    finally:
        _cleanup_libs(db)
        db.close()
        get_settings.cache_clear()


def test_delete_local_media_refuses_non_local(tmp_path: Path, monkeypatch) -> None:
    """delete_local_media still refuses strm; use delete_media_item for index-only."""
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
            number="X",
            source_type="strm",
            strm_target="https://example.com/x.mp4",
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        item_id = item.id

        with pytest.raises(HTTPException) as ei:
            delete_local_media(db, item)
        assert ei.value.status_code == 400
        assert db.get(MediaItem, item_id) is not None
        assert strm.exists()
    finally:
        _cleanup_libs(db)
        db.close()
        get_settings.cache_clear()


def test_ensure_path_outside_root_forbidden(tmp_path: Path, monkeypatch) -> None:
    init_db()
    media_root = tmp_path / "media"
    media_root.mkdir()
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"x")

    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("MEDIA_ROOT", str(media_root))
    get_settings.cache_clear()

    db = SessionLocal()
    try:
        lib = _seed_lib(db, path="local")
        item = MediaItem(
            library_id=lib.id,
            path=str(outside.resolve()),
            filename=outside.name,
            number="OUT",
            source_type="local",
        )
        db.add(item)
        db.commit()
        db.refresh(item)

        with pytest.raises(HTTPException) as ei:
            ensure_media_path_allowed(item, db)
        assert ei.value.status_code == 403
    finally:
        _cleanup_libs(db)
        db.close()
        get_settings.cache_clear()
