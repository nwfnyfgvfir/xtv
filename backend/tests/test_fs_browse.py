from __future__ import annotations

from pathlib import Path

import pytest

from app.config import get_settings
from app.services.fs_browse import BrowseError, list_subdirectories, normalize_rel_path


def _setup_media_root(tmp_path: Path, monkeypatch) -> Path:
    media_root = tmp_path / "media"
    media_root.mkdir()
    get_settings.cache_clear()
    monkeypatch.setenv("MEDIA_ROOT", str(media_root))
    get_settings.cache_clear()
    return media_root


def test_normalize_blank_and_separators() -> None:
    assert normalize_rel_path(None) == ""
    assert normalize_rel_path("") == ""
    assert normalize_rel_path("  ") == ""
    assert normalize_rel_path("strm\\jav") == "strm/jav"
    assert normalize_rel_path("strm/") == "strm"
    assert normalize_rel_path("strm//jav") == "strm/jav"


def test_normalize_rejects_traversal_and_absolute() -> None:
    with pytest.raises(BrowseError):
        normalize_rel_path("..")
    with pytest.raises(BrowseError):
        normalize_rel_path("local/../../etc")
    with pytest.raises(BrowseError):
        normalize_rel_path("/etc")
    with pytest.raises(BrowseError):
        normalize_rel_path("C:/data")


def test_list_root_and_nested(tmp_path: Path, monkeypatch) -> None:
    media_root = _setup_media_root(tmp_path, monkeypatch)
    (media_root / "local").mkdir()
    (media_root / "strm").mkdir()
    (media_root / "strm" / "jav").mkdir()
    (media_root / "strm" / "file.mp4").write_bytes(b"x")
    (media_root / ".hidden").mkdir()

    try:
        root = list_subdirectories("")
        assert root.path == ""
        assert root.parent is None
        names = {d.name for d in root.directories}
        assert names == {"local", "strm"}
        assert {d.path for d in root.directories} == {"local", "strm"}

        nested = list_subdirectories("strm")
        assert nested.path == "strm"
        assert nested.parent == ""
        assert len(nested.directories) == 1
        assert nested.directories[0].name == "jav"
        assert nested.directories[0].path == "strm/jav"

        deep = list_subdirectories("strm/jav")
        assert deep.path == "strm/jav"
        assert deep.parent == "strm"
        assert deep.directories == []

        # Windows-style separators in query
        via_bs = list_subdirectories("strm\\jav")
        assert via_bs.path == "strm/jav"
    finally:
        get_settings.cache_clear()


def test_empty_media_root(tmp_path: Path, monkeypatch) -> None:
    _setup_media_root(tmp_path, monkeypatch)
    try:
        result = list_subdirectories("")
        assert result.directories == []
        assert result.path == ""
    finally:
        get_settings.cache_clear()


def test_missing_and_not_dir(tmp_path: Path, monkeypatch) -> None:
    media_root = _setup_media_root(tmp_path, monkeypatch)
    (media_root / "only-file.txt").write_text("x", encoding="utf-8")
    try:
        with pytest.raises(BrowseError) as missing:
            list_subdirectories("nope")
        assert missing.value.status_code == 404

        with pytest.raises(BrowseError) as not_dir:
            list_subdirectories("only-file.txt")
        assert not_dir.value.status_code == 400
    finally:
        get_settings.cache_clear()


def test_traversal_via_list(tmp_path: Path, monkeypatch) -> None:
    _setup_media_root(tmp_path, monkeypatch)
    try:
        with pytest.raises(BrowseError):
            list_subdirectories("..")
        with pytest.raises(BrowseError):
            list_subdirectories("../")
    finally:
        get_settings.cache_clear()
