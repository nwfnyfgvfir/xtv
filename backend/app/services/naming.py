import re
import unicodedata
from pathlib import Path

SOURCE_NAME_VERSION = "source-filename-v1"


def source_name(filename: str) -> str:
    """Pass the original filename stem to metadata providers without rewriting it."""
    return Path(filename).stem


def subtitle_flag(filename: str) -> str | None:
    """Read explicit Chinese subtitle markers without changing the search text."""
    stem = unicodedata.normalize("NFKC", source_name(filename)).strip()
    if "中文字幕" in stem or "中字" in stem or re.search(r"[0-9]-?(?:ch|c)$", stem, re.IGNORECASE):
        return "C"
    return None
