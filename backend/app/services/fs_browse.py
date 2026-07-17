"""Safe directory listing under MEDIA_ROOT for library path picker."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings


class BrowseError(Exception):
    """Base error for directory browse; carry HTTP-ish status for the route layer."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class BrowseDirEntry:
    name: str
    path: str  # relative to MEDIA_ROOT, posix


@dataclass(frozen=True)
class BrowseDirsResult:
    path: str
    parent: str | None
    directories: list[BrowseDirEntry]


def normalize_rel_path(raw: str | None) -> str:
    """Normalize a relative path under MEDIA_ROOT.

    - blank → ""
    - ``\\`` → ``/``
    - strip leading/trailing slashes
    - reject absolute paths, empty segments, and ``..``
    """
    if raw is None:
        return ""
    s = str(raw).strip().replace("\\", "/")
    if not s or s == ".":
        return ""
    # Absolute: POSIX root or Windows drive (C:/...) or UNC
    if s.startswith("/") or (len(s) >= 2 and s[1] == ":"):
        raise BrowseError("path must be relative to MEDIA_ROOT", 400)
    if s.startswith("//"):
        raise BrowseError("path must be relative to MEDIA_ROOT", 400)
    parts: list[str] = []
    for part in s.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise BrowseError("path traversal is not allowed", 400)
        parts.append(part)
    return "/".join(parts)


def resolve_under_media_root(rel: str) -> Path:
    """Resolve *rel* under MEDIA_ROOT; raise BrowseError if outside/missing/not a dir."""
    root = get_settings().media_root_path.resolve()
    if not root.is_dir():
        raise BrowseError("MEDIA_ROOT is not a directory", 500)

    candidate = (root / rel).resolve() if rel else root
    try:
        candidate.relative_to(root)
    except ValueError as e:
        raise BrowseError("path is outside MEDIA_ROOT", 400) from e

    if not candidate.exists():
        raise BrowseError("directory not found", 404)
    if not candidate.is_dir():
        raise BrowseError("path is not a directory", 400)
    return candidate


def _parent_rel(rel: str) -> str | None:
    if not rel:
        return None
    if "/" not in rel:
        return ""
    return rel.rsplit("/", 1)[0]


def list_subdirectories(raw_path: str | None = "") -> BrowseDirsResult:
    """List one level of subdirectories under MEDIA_ROOT / raw_path."""
    rel = normalize_rel_path(raw_path)
    target = resolve_under_media_root(rel)

    entries: list[BrowseDirEntry] = []
    try:
        for child in target.iterdir():
            try:
                if not child.is_dir():
                    continue
            except OSError:
                continue
            name = child.name
            if name.startswith("."):
                continue
            child_rel = f"{rel}/{name}" if rel else name
            # Re-check containment after resolve (symlink escape)
            try:
                child.resolve().relative_to(get_settings().media_root_path.resolve())
            except ValueError:
                continue
            entries.append(BrowseDirEntry(name=name, path=child_rel.replace("\\", "/")))
    except OSError as e:
        raise BrowseError(f"failed to list directory: {e}", 500) from e

    entries.sort(key=lambda e: e.name.casefold())
    return BrowseDirsResult(path=rel, parent=_parent_rel(rel), directories=entries)
