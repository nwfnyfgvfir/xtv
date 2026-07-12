from __future__ import annotations

import logging
import re
from collections import OrderedDict
from threading import Lock
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

_CACHE: OrderedDict[str, str] = OrderedDict()
_CACHE_LOCK = Lock()
_CACHE_MAX = 512

# Preserve these tags as-is
_SKIP_TAGS = frozenset({"中文字幕", "中字", "無碼", "无码", "有码", "有碼"})

_KANA_RE = re.compile(r"[぀-ヿ]")
_CJK_RE = re.compile(r"[一-鿿]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def _cache_get(key: str) -> str | None:
    with _CACHE_LOCK:
        val = _CACHE.get(key)
        if val is not None:
            _CACHE.move_to_end(key)
        return val


def _cache_set(key: str, value: str) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = value
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)


def looks_chinese(text: str) -> bool:
    """Heuristic: mostly CJK, little kana → already Chinese enough to skip."""
    if not text or not text.strip():
        return True
    s = text.strip()
    cjk = len(_CJK_RE.findall(s))
    kana = len(_KANA_RE.findall(s))
    if kana > 0:
        return False
    if cjk == 0:
        return False
    # Mostly CJK characters among non-space content
    letters = cjk + len(_LATIN_RE.findall(s))
    return cjk >= max(2, letters * 0.5)


def _parse_gtx(data: Any) -> str | None:
    # Expected shape: [[["译","原",...], ...], ...]
    if not isinstance(data, list) or not data:
        return None
    chunks = data[0]
    if not isinstance(chunks, list):
        return None
    parts: list[str] = []
    for row in chunks:
        if isinstance(row, list) and row and isinstance(row[0], str):
            parts.append(row[0])
    out = "".join(parts).strip()
    return out or None


async def translate_text(text: str | None, *, target: str = "zh-CN") -> str | None:
    """Translate text via free Google gtx endpoint. Fail-open returns original."""
    if text is None:
        return None
    original = text
    s = text.strip()
    if not s:
        return original
    if looks_chinese(s):
        return original

    cache_key = f"{target}\0{s}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    url = (
        "https://translate.googleapis.com/translate_a/single"
        f"?client=gtx&sl=auto&tl={quote(target)}&dt=t&q={quote(s)}"
    )
    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=8.0)) as client:
                resp = await client.get(
                    url,
                    headers={"User-Agent": "TV-App/0.2", "Accept": "application/json"},
                )
            if resp.status_code in {429, 502, 503, 504} and attempt < 3:
                import asyncio

                await asyncio.sleep(0.6 * attempt)
                continue
            if not resp.is_success:
                last_err = RuntimeError(f"HTTP {resp.status_code}")
                break
            try:
                body = resp.json()
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                break
            translated = _parse_gtx(body)
            if translated:
                _cache_set(cache_key, translated)
                return translated
            last_err = RuntimeError("empty gtx parse")
            break
        except httpx.HTTPError as exc:
            last_err = exc
            if attempt < 3:
                import asyncio

                await asyncio.sleep(0.6 * attempt)
                continue
            break

    logger.warning("translate failed (keep original): %s", last_err)
    return original


async def translate_many(texts: list[str | None], *, target: str = "zh-CN") -> list[str | None]:
    out: list[str | None] = []
    for t in texts:
        out.append(await translate_text(t, target=target))
    return out


async def translate_tags(tags: list[str], *, target: str = "zh-CN") -> list[str]:
    result: list[str] = []
    for tag in tags:
        t = str(tag).strip()
        if not t:
            continue
        if t in _SKIP_TAGS:
            result.append(t)
            continue
        translated = await translate_text(t, target=target)
        result.append(translated or t)
    return result
