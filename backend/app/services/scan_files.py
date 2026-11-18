from __future__ import annotations

import os
from pathlib import Path

from app.config import get_settings
from app.models import Library, MediaItem


def root_path(lib: Library) -> Path:
    path = Path(lib.path)
    return (path if path.is_absolute() else get_settings().media_root_path / path).resolve()


def scan_scope_reason(path: Path, root: Path) -> str | None:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return "文件位于媒体库目录之外"
    if len(relative.parts) > 1:
        return "仅扫描媒体库根目录，不处理子目录文件"
    return None


def iter_files(root: Path, scopes: list[str] | None, *, checkpoint=None):
    """Yield root-level files without enumerating child directories."""
    seen: set[str] = set()
    for raw in scopes or [str(root)]:
        if checkpoint:
            checkpoint()
        target = Path(os.path.abspath(raw))
        if target != root:
            if target.parent != root or target.suffix.casefold() == ".ts":
                continue
            if str(target) not in seen and target.is_file():
                seen.add(str(target))
                yield target
            continue
        with os.scandir(root) as listing:
            for entry in listing:
                if checkpoint:
                    checkpoint()
                path = Path(entry.path)
                if entry.is_dir(follow_symlinks=False) or path.suffix.casefold() == ".ts":
                    continue
                if entry.is_symlink() and not entry.is_file():
                    continue
                if str(path) not in seen:
                    seen.add(str(path))
                    yield path


def apply_source_name(item: MediaItem, path: Path) -> None:
    from app.services.naming import source_name, subtitle_flag, SOURCE_NAME_VERSION

    query = source_name(path.name)
    if item.recognition_version == SOURCE_NAME_VERSION and item.number != query:
        item.scraped_at = None
    item.number = query
    item.subtitle_flag = subtitle_flag(path.name) or item.subtitle_flag
    item.number_source = "filename"
    item.recognition_notes = None
    item.recognition_version = SOURCE_NAME_VERSION
