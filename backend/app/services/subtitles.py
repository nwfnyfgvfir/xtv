from __future__ import annotations

import re
from pathlib import Path
from typing import Literal
from urllib.parse import quote

SubtitleType = Literal["srt", "vtt", "ass"]

SUBTITLE_EXTS = frozenset({"srt", "vtt", "ass"})

# Prefer Chinese-style tracks as default (filename tokens).
_CN_TOKENS = re.compile(
    r"(?i)(?:^|[.\-_])"
    r"(?:zh|chs|chi|cn|sc|simplified|中|中文|简|简体)"
    r"(?:$|[.\-_])"
    r"|中文字幕|中字"
)
# FOO-001-C.srt / FOO-001.C.srt / FOO-001_C.srt habit for Chinese subs.
_C_FLAG = re.compile(r"(?i)(?:^|[.\-_])C(?:$|[.\-_])")

_MIME: dict[str, str] = {
    "srt": "application/x-subrip; charset=utf-8",
    "vtt": "text/vtt; charset=utf-8",
    "ass": "text/x-ssa; charset=utf-8",
}


def subtitle_type(path: Path) -> SubtitleType:
    ext = path.suffix.lower().lstrip(".")
    if ext not in SUBTITLE_EXTS:
        raise ValueError(f"unsupported subtitle extension: {ext}")
    return ext  # type: ignore[return-value]


def mime_for_subtitle(path: Path) -> str:
    return _MIME.get(path.suffix.lower().lstrip("."), "text/plain; charset=utf-8")


def is_sidecar_match(media_stem: str, filename: str) -> bool:
    """True if filename is a same-dir sidecar for media stem S."""
    if not media_stem or not filename:
        return False
    name = Path(filename).name
    if name != filename:
        return False
    if any(sep in name for sep in ("/", "\\")) or ".." in name:
        return False
    path = Path(name)
    ext = path.suffix.lower().lstrip(".")
    if ext not in SUBTITLE_EXTS:
        return False
    t = path.stem
    s = media_stem
    if t.casefold() == s.casefold():
        return True
    tl, sl = t.casefold(), s.casefold()
    return tl.startswith(sl + ".") or tl.startswith(sl + "-") or tl.startswith(sl + "_")


def discover_sidecar_subtitles(media_path: Path) -> list[Path]:
    """List matching subtitle files next to the media file."""
    media_path = Path(media_path)
    parent = media_path.parent
    stem = media_path.stem
    if not parent.is_dir():
        return []
    found: list[Path] = []
    try:
        entries = list(parent.iterdir())
    except OSError:
        return []
    for p in entries:
        try:
            if not p.is_file():
                continue
        except OSError:
            continue
        if is_sidecar_match(stem, p.name):
            found.append(p)
    found.sort(key=lambda x: x.name.casefold())
    return found


def is_chinese_subtitle_name(filename: str) -> bool:
    name = Path(filename).name
    stem = Path(name).stem
    if _CN_TOKENS.search(stem) or _CN_TOKENS.search(name):
        return True
    # FOO-001-C → middle token C after media stem is treated as Chinese.
    if _C_FLAG.search(stem) or re.search(r"(?i)-C(?:-|$)", stem):
        return True
    return False


def subtitle_display_name(media_stem: str, path: Path) -> str:
    """Human label for UI: 中文 / 字幕 / raw middle token."""
    t = path.stem
    s = media_stem
    middle = ""
    if t.casefold() == s.casefold():
        middle = ""
    elif t.casefold().startswith(s.casefold()):
        rest = t[len(s) :]
        if rest and rest[0] in ".-_":
            middle = rest[1:]
        else:
            middle = rest
    else:
        middle = t

    if not middle:
        return "字幕"
    if is_chinese_subtitle_name(path.name) or is_chinese_subtitle_name(f"x-{middle}.srt"):
        # Single C marker
        if re.fullmatch(r"(?i)C", middle) or re.fullmatch(r"(?i)C(?:[.\-_].*)?", middle):
            return "中文"
        low = middle.casefold()
        if any(tok in low for tok in ("zh", "chs", "chi", "cn", "sc", "中", "简")) or "中" in middle:
            return "中文"
        if any(tok in low for tok in ("cht", "tc", "繁")) or "繁" in middle:
            return "繁体"
        return "中文"
    if re.fullmatch(r"(?i)cht|tc|traditional", middle) or "繁" in middle:
        return "繁体"
    return middle


def sort_and_pick_default(paths: list[Path]) -> list[tuple[Path, bool]]:
    """Stable sort by name; mark one default (Chinese preferred)."""
    ordered = sorted(paths, key=lambda p: p.name.casefold())
    default_idx = 0
    for i, p in enumerate(ordered):
        if is_chinese_subtitle_name(p.name):
            default_idx = i
            break
    return [(p, i == default_idx) for i, p in enumerate(ordered)]


def resolve_sidecar_file(media_path: Path, filename: str) -> Path:
    """
    Resolve a safe sibling subtitle path.
    Raises ValueError on invalid / non-matching / missing files.
    """
    media_path = Path(media_path).resolve()
    raw = (filename or "").strip()
    if not raw:
        raise ValueError("empty filename")
    # basename only — reject separators and ..
    if "/" in raw or "\\" in raw or raw in (".", "..") or ".." in raw:
        raise ValueError("path traversal rejected")
    base = Path(raw).name
    if base != raw:
        raise ValueError("path traversal rejected")

    if not is_sidecar_match(media_path.stem, base):
        raise ValueError("filename does not match media sidecar rule")

    parent = media_path.parent.resolve()
    candidate = (parent / base).resolve()
    if candidate.parent != parent:
        raise ValueError("not a sibling of media file")
    if candidate.suffix.lower().lstrip(".") not in SUBTITLE_EXTS:
        raise ValueError("unsupported extension")
    if not candidate.is_file():
        raise ValueError("file missing")
    return candidate


def build_subtitle_tracks(media_id: int, media_path: Path) -> list[dict]:
    """Build serializable track dicts for PlayInfo (url relative to API root)."""
    paths = discover_sidecar_subtitles(media_path)
    if not paths:
        return []
    stem = Path(media_path).stem
    tracks: list[dict] = []
    for sub_path, is_default in sort_and_pick_default(paths):
        typ = subtitle_type(sub_path)
        tracks.append(
            {
                "name": subtitle_display_name(stem, sub_path),
                "url": f"/api/stream/{media_id}/subtitle?file={quote(sub_path.name)}",
                "type": typ,
                "filename": sub_path.name,
                "default": is_default,
            }
        )
    return tracks
