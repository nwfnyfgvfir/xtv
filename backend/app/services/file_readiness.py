from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import FileObservation, Library, MediaItem, utcnow
from app.services.strm import read_strm_target
from app.services.ts_files import TsGuard, inspect_directory

TEMP_SUFFIXES = {".tmp", ".part", ".crdownload", ".ytdlp", ".partial", ".aria2", ".!qb", ".!ut", ".td"}
TEMP_NAME = re.compile(r"(?i)(?:[._-](?:part|partial|tmp|temp|download)|\.f\d{1,5})\.[a-z0-9]{2,8}$")
TEMP_DIRS = {'temp', '.temp', '_temp', '_tmp', 'temporary', 'download_temp', 'downloads_temp',
             'downloads_tmp', 'download_cache', 'downloading', '.downloading', '临时', '临时目录',
             '下载临时', '下载临时目录', '临时下载', '下载缓存'}
_TEMP_DIR = re.compile(r'(?i)^[._]?(?:tmp|temp)(?:[._-](?:\d{6,}|[a-f0-9]{8,}))?$')


def ignored_dirs(lib: Library | None = None) -> set[str]:
    raw = lib.ignore_dirs if lib and lib.ignore_dirs is not None else get_settings().download_ignore_dirs
    return {part.strip().casefold() for part in raw.split(",") if part.strip()} | TEMP_DIRS


def ignored_directory(name: str, lib: Library | None = None) -> bool:
    return name.casefold() in ignored_dirs(lib) or bool(_TEMP_DIR.fullmatch(name))


def settle_seconds(lib: Library) -> int:
    return max(0, lib.file_settle_seconds if lib.file_settle_seconds is not None else get_settings().file_settle_seconds)


def root_path(lib: Library) -> Path:
    path = Path(lib.path)
    return (path if path.is_absolute() else get_settings().media_root_path / path).resolve()


def ignored_reason(path: Path, root: Path, lib: Library | None = None) -> str | None:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return "文件位于媒体库目录之外"
    if any(ignored_directory(part, lib) for part in relative.parts[:-1]):
        return "位于排除的下载临时目录"
    if path.suffix.casefold() in TEMP_SUFFIXES:
        return "下载临时后缀或控制文件"
    if path.name.startswith("."):
        return "隐藏媒体文件，可能为过程文件"
    if TEMP_NAME.search(path.name):
        return "文件名包含下载分片或临时标记"
    return None


def control_target(path: Path) -> Path | None:
    return path.with_suffix("") if path.suffix.casefold() in {".aria2"} else None


def iter_files(root: Path, scopes: list[str] | None, lib: Library, *, checkpoint=None, guard=None, on_deferred=None):
    """Yield paths without reading media contents; never walk ignored subtrees."""
    seen: set[str] = set()
    guard = guard or TsGuard(checkpoint)
    deferred_dirs = set()
    def allowed(path):
        if ignored_reason(path, root, lib) and not control_target(path):
            return False
        verdict = guard.classify(path, lib)
        if verdict:
            if verdict[0] == 'waiting' and on_deferred and path.parent not in deferred_dirs:
                deferred_dirs.add(path.parent)
                on_deferred(path, verdict[1])
            return False
        return True
    for raw in scopes or [str(root)]:
        if checkpoint:
            checkpoint()
        target = Path(raw).resolve()
        if not target.is_relative_to(root):
            continue
        if ignored_reason(target, root, lib) and not control_target(target):
            continue
        if target.is_file():
            if str(target) not in seen and allowed(target):
                seen.add(str(target))
                yield target
            continue
        if not target.is_dir() or target != root and ignored_directory(target.name, lib):
            continue
        stack = [target]
        while stack:
            if checkpoint:
                checkpoint()
            directory = stack.pop()
            entries = []
            with os.scandir(directory) as listing:
                for entry in listing:
                    if checkpoint:
                        checkpoint()
                    entries.append(entry)
            if any(entry.name.lower().endswith('.ts') for entry in entries):
                guard.directories[directory] = inspect_directory(directory, [entry.name for entry in entries], checkpoint)
            directories = []
            for entry in entries:
                if checkpoint:
                    checkpoint()
                path = Path(entry.path)
                if entry.is_dir(follow_symlinks=False):
                    if not ignored_directory(entry.name, lib):
                        directories.append(path)
                    continue
                if entry.is_symlink() and not entry.is_file():
                    continue
                if str(path) not in seen and allowed(path):
                    seen.add(str(path))
                    yield path
            stack.extend(reversed(directories))


@dataclass
class FileCheck:
    state: str
    reason: str = ""
    stat: os.stat_result | None = None
    strm_target: str | None = None


class FileDeferred(Exception):
    def __init__(self, check: FileCheck):
        super().__init__(check.reason)
        self.check = check


def check_file(db: Session, lib: Library, path: Path, *, now: datetime | None = None,
               readonly: bool = False, confirmed: bool = False, guard=None) -> FileCheck:
    now = (now or utcnow()).replace(tzinfo=None)
    root = root_path(lib)
    reason = ignored_reason(path, root, lib)
    if reason:
        return FileCheck("ignored", reason)
    if path.suffix.lower().lstrip(".") not in get_settings().extension_set:
        return FileCheck("unsupported", "不在扫描扩展名白名单中")
    try:
        if verdict := (guard or TsGuard()).classify(path, lib):
            return FileCheck(*verdict)
        stat = path.stat()
        if not path.is_file():
            return FileCheck("ignored", "不是普通文件")
    except FileNotFoundError:
        if not readonly:
            observation = db.query(FileObservation).filter_by(library_id=lib.id, path=str(path)).one_or_none()
            if observation and observation.state != "missing":
                observation.state, observation.reason, observation.next_check_at = "missing", "文件已不存在", None
        return FileCheck("missing", "文件已不存在")
    except OSError:
        if not readonly:
            observation = db.query(FileObservation).filter_by(library_id=lib.id, path=str(path)).one_or_none()
            if observation is None:
                observation = FileObservation(library_id=lib.id, path=str(path))
                db.add(observation)
            observation.state, observation.reason = "unreadable", "文件暂时不可读，保留已有索引"
            observation.next_check_at = now + timedelta(seconds=120)
        return FileCheck("unreadable", "文件暂时不可读，保留已有索引")
    if not path.resolve().is_relative_to(root):
        return FileCheck("ignored", "文件链接指向媒体库之外")
    observation = db.query(FileObservation).filter_by(library_id=lib.id, path=str(path)).one_or_none()
    identical = observation is not None and observation.size == stat.st_size and observation.mtime_ns == str(stat.st_mtime_ns)
    changed_at = observation.changed_at.replace(tzinfo=None) if identical else now
    if readonly and observation is None:
        changed_at = datetime.utcfromtimestamp(stat.st_mtime)
    target = read_strm_target(path) if path.suffix.lower() == ".strm" else None
    try:
        control = any(path.with_name(path.name + suffix).exists() for suffix in (".aria2", ".part", ".!qB", ".!ut"))
    except OSError:
        control = True
    reason = ""
    if control:
        reason = "存在对应的下载状态文件"
    elif stat.st_size == 0:
        reason = "零字节文件，等待写入完成"
    elif path.suffix.lower() == ".strm":
        try:
            parsed = urlsplit(target or "")
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                reason = "STRM 尚无有效 HTTP(S) 播放地址"
        except ValueError:
            reason = "STRM 播放地址尚未就绪"
    complete_signal = confirmed or identical and observation.confirmed
    if not reason and not complete_signal and (now - changed_at).total_seconds() < settle_seconds(lib):
        reason = f"等待文件大小与修改时间连续稳定 {settle_seconds(lib)} 秒"
    state = "waiting" if reason else "ready"
    if not readonly:
        if observation is None:
            observation = FileObservation(library_id=lib.id, path=str(path))
            db.add(observation)
        if not identical or observation.state != state or observation.reason != reason or confirmed:
            observation.size, observation.mtime_ns = stat.st_size, str(stat.st_mtime_ns)
            observation.changed_at, observation.state, observation.reason = changed_at, state, reason
            observation.confirmed = bool(complete_signal and not control)
            observation.next_check_at = now + timedelta(seconds=max(30, settle_seconds(lib))) if reason else None
        elif reason and observation.next_check_at and observation.next_check_at.replace(tzinfo=None) <= now:
            observation.next_check_at = now + timedelta(seconds=max(30, settle_seconds(lib)))
    return FileCheck(state, reason, stat, target)


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
