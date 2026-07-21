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
    """Return source_type for a .strm target. Always 'strm' (HTTP or path)."""
    _ = target  # target content only matters at play time
    return "strm"
