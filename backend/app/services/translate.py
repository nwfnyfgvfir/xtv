from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
from collections import OrderedDict
from threading import Lock
from typing import Any
from urllib.parse import quote

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_CACHE: OrderedDict[str, str] = OrderedDict()
_CACHE_LOCK = Lock()
_CACHE_MAX = 512

# Preserve these tags as-is
_SKIP_TAGS = frozenset({"中文字幕", "中字", "無碼", "无码", "有码", "有碼"})

_KANA_RE = re.compile(r"[぀-ヿ]")
_CJK_RE = re.compile(r"[一-鿿]")
_LATIN_RE = re.compile(r"[A-Za-z]")

_EDGE_AUTH_URL = "https://edge.microsoft.com/translate/auth"
_EDGE_TRANSLATE_URL = "https://api-edge.cognitive.microsofttranslator.com/translate"
_EDGE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/172.16.1.5 Safari/537.36 Edg/172.16.1.5"
)
_TOKEN_SKEW = 60.0
_TOKEN_FALLBACK_TTL = 540.0  # ~9 min if JWT exp cannot be parsed

_token_lock = Lock()
_edge_token: str | None = None
_edge_token_exp: float = 0.0

_HTTP_TIMEOUT = httpx.Timeout(12.0, connect=8.0)


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


def _parse_bing(data: Any) -> str | None:
    # Azure Translator v3: [{"translations":[{"text":"...","to":"zh-Hans"}], ...}]
    if not isinstance(data, list) or not data:
        return None
    first = data[0]
    if not isinstance(first, dict):
        return None
    translations = first.get("translations")
    if not isinstance(translations, list) or not translations:
        return None
    parts: list[str] = []
    for item in translations:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            parts.append(item["text"])
    out = "".join(parts).strip()
    return out or None


def _map_target_for_bing(target: str) -> str:
    t = (target or "").strip()
    if t in ("zh-CN", "zh", "zh-Hans"):
        return "zh-Hans"
    if t in ("zh-TW", "zh-Hant"):
        return "zh-Hant"
    return t or "zh-Hans"


def _parse_jwt_exp(token: str) -> float | None:
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload_b64 = parts[1]
        pad = "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + pad))
        exp = payload.get("exp")
        if isinstance(exp, (int, float)):
            return float(exp)
    except Exception:  # noqa: BLE001
        return None
    return None


def _resolved_provider() -> str:
    try:
        raw = (get_settings().translate_provider or "google").strip().lower()
    except Exception:  # noqa: BLE001
        return "google"
    return raw if raw in ("google", "bing") else "google"


async def _fetch_edge_token(client: httpx.AsyncClient) -> str:
    resp = await client.get(
        _EDGE_AUTH_URL,
        headers={"User-Agent": _EDGE_UA, "Accept": "*/*"},
    )
    if not resp.is_success:
        raise RuntimeError(f"edge auth HTTP {resp.status_code}")
    token = (resp.text or "").strip()
    if not token or token.count(".") < 2:
        raise RuntimeError("edge auth empty/invalid token")
    return token


async def _get_edge_token(client: httpx.AsyncClient, *, force: bool = False) -> str:
    global _edge_token, _edge_token_exp
    now = time.time()
    with _token_lock:
        if (
            not force
            and _edge_token
            and now < (_edge_token_exp - _TOKEN_SKEW)
        ):
            return _edge_token

    token = await _fetch_edge_token(client)
    exp = _parse_jwt_exp(token) or (time.time() + _TOKEN_FALLBACK_TTL)
    with _token_lock:
        _edge_token = token
        _edge_token_exp = exp
        return _edge_token


async def _translate_google_gtx(text: str, target: str) -> str | None:
    url = (
        "https://translate.googleapis.com/translate_a/single"
        f"?client=gtx&sl=auto&tl={quote(target)}&dt=t&q={quote(text)}"
    )
    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.get(
                    url,
                    headers={"User-Agent": "TV-App/0.2", "Accept": "application/json"},
                )
            if resp.status_code in {429, 502, 503, 504} and attempt < 3:
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
                return translated
            last_err = RuntimeError("empty gtx parse")
            break
        except httpx.HTTPError as exc:
            last_err = exc
            if attempt < 3:
                await asyncio.sleep(0.6 * attempt)
                continue
            break

    logger.warning("google translate failed: %s", last_err)
    return None


async def _translate_bing(text: str, target: str) -> str | None:
    to_lang = _map_target_for_bing(target)
    url = f"{_EDGE_TRANSLATE_URL}?api-version=3.0&to={quote(to_lang)}"
    body = [{"Text": text}]
    last_err: Exception | None = None
    force_token = False

    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                try:
                    token = await _get_edge_token(client, force=force_token)
                except Exception as exc:  # noqa: BLE001
                    last_err = exc
                    if attempt < 3:
                        await asyncio.sleep(0.6 * attempt)
                        force_token = True
                        continue
                    break
                force_token = False
                resp = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                        "User-Agent": _EDGE_UA,
                        "Accept": "application/json",
                    },
                    json=body,
                )
            if resp.status_code == 401 and attempt < 3:
                force_token = True
                await asyncio.sleep(0.3)
                continue
            if resp.status_code in {429, 502, 503, 504} and attempt < 3:
                await asyncio.sleep(0.6 * attempt)
                continue
            if not resp.is_success:
                last_err = RuntimeError(f"HTTP {resp.status_code}")
                break
            try:
                data = resp.json()
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                break
            translated = _parse_bing(data)
            if translated:
                return translated
            last_err = RuntimeError("empty bing parse")
            break
        except httpx.HTTPError as exc:
            last_err = exc
            if attempt < 3:
                await asyncio.sleep(0.6 * attempt)
                continue
            break

    logger.warning("bing translate failed: %s", last_err)
    return None


async def translate_text(text: str | None, *, target: str = "zh-CN") -> str | None:
    """Translate text via configured free provider. Fail-open returns original."""
    if text is None:
        return None
    original = text
    s = text.strip()
    if not s:
        return original
    if looks_chinese(s):
        return original

    provider = _resolved_provider()
    cache_key = f"{provider}\0{target}\0{s}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    if provider == "bing":
        translated = await _translate_bing(s, target)
    else:
        translated = await _translate_google_gtx(s, target)

    if translated:
        _cache_set(cache_key, translated)
        return translated

    logger.warning("translate failed (keep original): provider=%s", provider)
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
