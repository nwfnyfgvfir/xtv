import re
import unicodedata
from pathlib import Path

SOURCE_NAME_VERSION = "source-filename-v1"
_CHINESE_SUBTITLE_SUFFIX = re.compile(r"(?<=[0-9０-９])[-－]?[cｃ](?:[hｈ])?$", re.IGNORECASE)


def source_name(filename: str) -> str:
    """Pass the original filename stem to metadata providers without rewriting it."""
    return Path(filename).stem


def subtitle_flag(filename: str) -> str | None:
    """Read explicit Chinese subtitle markers without changing the search text."""
    stem = unicodedata.normalize("NFKC", source_name(filename)).strip()
    if "中文字幕" in stem or "中字" in stem or _CHINESE_SUBTITLE_SUFFIX.search(stem):
        return "C"
    return None


def strip_chinese_subtitle_suffix(query: str) -> str:
    """Remove only a terminal numeric C/CH marker from an already-built query."""
    return _CHINESE_SUBTITLE_SUFFIX.sub("", query)
