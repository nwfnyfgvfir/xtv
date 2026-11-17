"""Identify download fragments from directory context, without reading TS data."""
from __future__ import annotations

import os
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

_NUMERIC = re.compile(r"^\d{1,16}(?:[-_]\d{1,16})*$")
_FRAGMENT = re.compile(r"(?i)^((?:seg(?:ment)?|chunk|frag(?:ment)?|part|index|media|hls)[._-]?)\d+(?:[._-]\d+)*$")
_HASH = re.compile(r"(?i)^[a-f0-9]{24,64}$")
_TRAILING = re.compile(r"^(.+[._-])\d{3,}$")
_cache: OrderedDict[str, tuple[int, float, 'TsDirectory']] = OrderedDict()
_cache_lock = threading.Lock()


def fragment_family(name: str) -> str | None:
    stem = Path(name).stem
    if _NUMERIC.fullmatch(stem):
        return 'numeric'
    if match := _FRAGMENT.fullmatch(stem):
        return match[1].casefold()
    if _HASH.fullmatch(stem):
        return 'hash'
    if match := _TRAILING.fullmatch(stem):
        # ABP-001_00001 is a potential fragment; ABP-00001 is a movie code.
        if re.search(r"\d[._-]$", match[1]):
            return match[1].casefold()
    return None


@dataclass
class TsDirectory:
    segments: set[str] = field(default_factory=set)
    families: dict[str, list[str]] = field(default_factory=dict)

    def classify(self, path: Path, policy: str = 'auto') -> tuple[str, str] | None:
        if path.name.casefold() in self.segments:
            return 'ignored', 'HLS 播放清单中的 TS 分片，不作为独立影片入库'
        family = fragment_family(path.name)
        if policy != 'complete' and family in self.families:
            count = len(self.families[family])
            return 'waiting', f'同目录 {count} 个编号或哈希 TS 疑似分片，已整组暂缓；若均为完整影片，请将 TS 策略设为“完整文件”'
        return None


def inspect_directory(directory: Path, names: list[str] | None = None, checkpoint=None) -> TsDirectory:
    stamp = directory.stat().st_mtime_ns
    key, now = str(directory), time.monotonic()
    with _cache_lock:
        cached = _cache.get(key)
        if cached and cached[0] == stamp and now - cached[1] < 5:
            _cache.move_to_end(key)
            return cached[2]
    if names is None:
        names = []
        with os.scandir(directory) as entries:
            for entry in entries:
                if checkpoint:
                    checkpoint()
                names.append(entry.name)
    state = TsDirectory()
    for name in names:
        if checkpoint:
            checkpoint()
        if Path(name).suffix.casefold() == '.ts' and (family := fragment_family(name)):
            state.families.setdefault(family, []).append(name)
    state.families = {key: values for key, values in state.families.items() if len(values) >= 8}
    for name in [name for name in names if Path(name).suffix.casefold() == '.m3u8'][:8]:
        if checkpoint:
            checkpoint()
        playlist = directory / name
        if playlist.is_symlink():
            continue
        try:
            with playlist.open('r', encoding='utf-8-sig', errors='ignore') as handle:
                content = handle.read(131072)
        except OSError:
            continue
        if (not content.lstrip().startswith('#EXTM3U') or '#EXTINF:' not in content
                or not re.search(r'(?m)^#EXT-X-[A-Z-]+(?::|$)', content)):
            continue
        references = set()
        for line in content.splitlines():
            if checkpoint:
                checkpoint()
            value = line.strip()
            if not value or value.startswith('#'):
                continue
            try:
                target = PurePosixPath(unquote(urlsplit(value).path)).name
            except ValueError:
                continue
            if target.lower().endswith('.ts'):
                references.add(target.casefold())
        if len(references) >= 2:
            state.segments.update(references)
    with _cache_lock:
        _cache[key] = stamp, now, state
        _cache.move_to_end(key)
        while len(_cache) > 32:
            _cache.popitem(last=False)
    return state


class TsGuard:
    def __init__(self, checkpoint=None):
        self.directories: dict[Path, TsDirectory] = {}
        self.checkpoint = checkpoint

    def classify(self, path: Path, lib) -> tuple[str, str] | None:
        if path.suffix.casefold() != '.ts':
            return None
        if path.parent not in self.directories:
            try:
                self.directories[path.parent] = inspect_directory(path.parent, checkpoint=self.checkpoint)
            except FileNotFoundError:
                return None
        return self.directories[path.parent].classify(path, getattr(lib, 'ts_policy', None) or 'auto')
