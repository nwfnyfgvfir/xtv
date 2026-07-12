from pathlib import Path

from app.services.strm import classify_strm_target, read_strm_target


def test_classify_http():
    assert classify_strm_target("https://cdn.example.com/a.mp4") == "strm"
    assert classify_strm_target("http://x/y") == "strm"


def test_classify_path():
    assert classify_strm_target("/cloud/jav/SSIS-001/SSIS-001.mp4") == "alist"


def test_read_strm(tmp_path: Path):
    f = tmp_path / "a.strm"
    f.write_text("# comment\n\nhttps://example.com/v.mp4\n", encoding="utf-8")
    assert read_strm_target(f) == "https://example.com/v.mp4"
