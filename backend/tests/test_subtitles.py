from __future__ import annotations

from pathlib import Path

import pytest

from app.services.subtitles import (
    build_subtitle_tracks,
    discover_sidecar_subtitles,
    is_chinese_subtitle_name,
    is_sidecar_match,
    resolve_sidecar_file,
    sort_and_pick_default,
    subtitle_display_name,
)


def test_sidecar_match_exact_and_separators() -> None:
    assert is_sidecar_match("FOO-001", "FOO-001.srt")
    assert is_sidecar_match("FOO-001", "FOO-001.zh.srt")
    assert is_sidecar_match("FOO-001", "FOO-001-C.srt")
    assert is_sidecar_match("FOO-001", "FOO-001_en.ass")
    assert is_sidecar_match("FOO-001", "foo-001-C.vtt")  # casefold


def test_sidecar_match_rejects_unrelated() -> None:
    assert not is_sidecar_match("FOO-001", "FOO-001x.srt")
    assert not is_sidecar_match("FOO-001", "BAR-001.srt")
    assert not is_sidecar_match("FOO-001", "FOO-001.txt")
    assert not is_sidecar_match("FOO-001", "../FOO-001.srt")
    assert not is_sidecar_match("FOO-001", "sub/FOO-001.srt")


def test_discover_and_default_c(tmp_path: Path) -> None:
    media = tmp_path / "FOO-001.mp4"
    media.write_bytes(b"x")
    (tmp_path / "FOO-001.en.srt").write_text("en", encoding="utf-8")
    (tmp_path / "FOO-001-C.srt").write_text("zh", encoding="utf-8")
    (tmp_path / "other.srt").write_text("nope", encoding="utf-8")
    (tmp_path / "FOO-001x.srt").write_text("nope", encoding="utf-8")

    found = discover_sidecar_subtitles(media)
    names = {p.name for p in found}
    assert names == {"FOO-001.en.srt", "FOO-001-C.srt"}

    ranked = sort_and_pick_default(found)
    defaults = [p.name for p, d in ranked if d]
    assert defaults == ["FOO-001-C.srt"]
    assert is_chinese_subtitle_name("FOO-001-C.srt")
    assert subtitle_display_name("FOO-001", Path("FOO-001-C.srt")) == "中文"


def test_resolve_safe(tmp_path: Path) -> None:
    media = tmp_path / "FOO-001.mp4"
    media.write_bytes(b"x")
    sub = tmp_path / "FOO-001-C.srt"
    sub.write_text("1", encoding="utf-8")
    other = tmp_path / "unrelated.srt"
    other.write_text("2", encoding="utf-8")

    assert resolve_sidecar_file(media, "FOO-001-C.srt") == sub.resolve()

    with pytest.raises(ValueError):
        resolve_sidecar_file(media, "../FOO-001-C.srt")
    with pytest.raises(ValueError):
        resolve_sidecar_file(media, "sub/FOO-001-C.srt")
    with pytest.raises(ValueError):
        resolve_sidecar_file(media, "unrelated.srt")
    with pytest.raises(ValueError):
        resolve_sidecar_file(media, "missing.srt")


def test_build_tracks_urls(tmp_path: Path) -> None:
    media = tmp_path / "demo.mp4"
    media.write_bytes(b"x")
    (tmp_path / "demo.srt").write_text("a", encoding="utf-8")
    (tmp_path / "demo.zh.srt").write_text("b", encoding="utf-8")

    tracks = build_subtitle_tracks(42, media)
    assert len(tracks) == 2
    assert all(t["url"].startswith("/api/stream/42/subtitle?file=") for t in tracks)
    assert any(t["default"] for t in tracks)
    assert sum(1 for t in tracks if t["default"]) == 1
    zh = next(t for t in tracks if t["default"])
    assert "zh" in zh["filename"].lower() or zh["name"] == "中文"
