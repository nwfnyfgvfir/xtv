from __future__ import annotations

from pathlib import Path


def read_strm_target(path: Path) -> str | None:
    """Read first non-empty, non-comment line from a .strm file."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        return s
    return None


def classify_strm_target(target: str) -> str:
    """Return source_type: 'strm' for http(s), 'alist' for path-like."""
    t = target.strip()
    lower = t.lower()
    if lower.startswith("http://") or lower.startswith("https://"):
        return "strm"
    return "alist"
