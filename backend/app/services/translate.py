from __future__ import annotations

import asyncio
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

_EDGE_TRANSLATE_TEXT_URL = "https://edge.microsoft.com/translate/translatetext"
_EDGE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
)
_GOOGLE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
_GOOGLE_BASE_URLS = (
    "https://translate.googleapis.com/translate_a/single",
    "https://translate.google.com/translate_a/single",
)
_GOOGLE_HEADERS = {
    "User-Agent": _GOOGLE_UA,
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://translate.google.com/",
}
_GOOGLE_MIN_INTERVAL = 0.45  # seconds between gtx calls (title/plot/tags burst)
_GOOGLE_MAX_ATTEMPTS = 5
_DEEPL_MIN_INTERVAL = 0.8  # DeepLX public pool is stricter on burst
_DEEPL_MAX_ATTEMPTS = 5
_BING_MIN_INTERVAL = 0.45
_BING_MAX_ATTEMPTS = 5
_DEEPL_FREE_URL = "https://api-free.deepl.com/v2/translate"
_DEEPL_PRO_URL = "https://api.deepl.com/v2/translate"
_VALID_PROVIDERS = frozenset({"google", "bing", "deepl"})
_RETRYABLE_STATUS = frozenset({429, 502, 503, 504})

_google_lock = asyncio.Lock()
_google_last_at: float = 0.0

_deepl_lock = asyncio.Lock()
_deepl_last_at: float = 0.0

_bing_lock = asyncio.Lock()
_bing_last_at: float = 0.0

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


def _parse_deepl(data: Any) -> str | None:
    # {"translations":[{"detected_source_language":"JA","text":"..."}]}
    if not isinstance(data, dict):
        return None
    translations = data.get("translations")
    if not isinstance(translations, list) or not translations:
        return None
    first = translations[0]
    if not isinstance(first, dict):
        return None
    text = first.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    return None


def _parse_deeplx(data: Any) -> str | None:
    # DeepLX native: {"code":200,"data":"..."}
    if not isinstance(data, dict):
        return None
    code = data.get("code")
    if code not in (200, "200"):
        return None
    text = data.get("data")
    if isinstance(text, str) and text.strip():
        return text.strip()
    return None


def _map_target_for_bing(target: str) -> str:
    t = (target or "").strip()
    if t in ("zh-CN", "zh", "zh-Hans"):
        return "zh-Hans"
    if t in ("zh-TW", "zh-Hant"):
        return "zh-Hant"
    return t or "zh-Hans"


def _map_target_for_deepl(target: str) -> str:
    t = (target or "").strip()
    if t in ("zh-TW", "zh-Hant"):
        return "ZH-HANT"
    return "ZH"


def _resolved_provider() -> str:
    try:
        raw = (get_settings().translate_provider or "google").strip().lower()
    except Exception:  # noqa: BLE001
        return "google"
    return raw if raw in _VALID_PROVIDERS else "google"


def _google_proxy_url() -> str | None:
    """Return proxy URL for Google gtx when enabled; otherwise None (direct)."""
    try:
        s = get_settings()
    except Exception:  # noqa: BLE001
        return None
    if not bool(getattr(s, "translate_google_proxy", False)):
        return None
    url = (getattr(s, "translate_google_proxy_url", None) or "").strip()
    return url or None


def _deepl_api_key() -> str | None:
    try:
        s = get_settings()
        key = (getattr(s, "translate_deepl_api_key", None) or "").strip()
    except Exception:  # noqa: BLE001
        return None
    return key or None


def _deepl_proxy_url() -> str | None:
    try:
        s = get_settings()
    except Exception:  # noqa: BLE001
        return None
    if not bool(getattr(s, "translate_deepl_proxy", False)):
        return None
    url = (getattr(s, "translate_deepl_proxy_url", None) or "").strip()
    return url or None


def _normalize_deepl_api_url(raw: str) -> str:
    """Normalize custom DeepL endpoint URL; do not mutate paths ending in /translate."""
    url = (raw or "").strip().rstrip("/")
    if not url:
        return ""
    lower = url.lower()
    if lower.endswith("/v2/translate") or lower.endswith("/translate"):
        return url
    return f"{url}/v2/translate"


def _deepl_api_mode(url: str) -> str:
    """Detect official DeepL vs DeepLX native API from endpoint URL."""
    lower = (url or "").lower()
    if lower.endswith("/v2/translate") or "deepl.com" in lower:
        return "official"
    if "deeplx" in lower or lower.endswith("/translate"):
        return "deeplx"
    return "official"


def _deepl_translate_url() -> str:
    try:
        s = get_settings()
        custom = _normalize_deepl_api_url(getattr(s, "translate_deepl_api_url", "") or "")
        if custom:
            return custom
    except Exception:  # noqa: BLE001
        pass
    key = _deepl_api_key() or ""
    if key.endswith(":fx"):
        return _DEEPL_FREE_URL
    try:
        s = get_settings()
        use_free = bool(getattr(s, "translate_deepl_free", True))
    except Exception:  # noqa: BLE001
        use_free = True
    return _DEEPL_FREE_URL if use_free else _DEEPL_PRO_URL


def _deepl_client_kwargs() -> dict[str, Any]:
    client_kwargs: dict[str, Any] = {"timeout": _HTTP_TIMEOUT}
    proxy = _deepl_proxy_url()
    if proxy:
        client_kwargs["proxy"] = proxy
    return client_kwargs


def _retry_delay_seconds(attempt: int, status_code: int, resp: httpx.Response | None) -> float:
    """Backoff for retryable HTTP statuses; 429 uses longer waits."""
    if resp is not None:
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return max(float(retry_after), 1.0)
            except ValueError:
                pass
    if status_code == 429:
        return min(2.0 * (2 ** (attempt - 1)), 30.0)
    return 0.6 * attempt


async def _google_throttle() -> None:
    global _google_last_at
    async with _google_lock:
        now = time.monotonic()
        wait = _GOOGLE_MIN_INTERVAL - (now - _google_last_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _google_last_at = time.monotonic()


async def _deepl_throttle() -> None:
    global _deepl_last_at
    async with _deepl_lock:
        now = time.monotonic()
        wait = _DEEPL_MIN_INTERVAL - (now - _deepl_last_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _deepl_last_at = time.monotonic()


async def _bing_throttle() -> None:
    global _bing_last_at
    async with _bing_lock:
        now = time.monotonic()
        wait = _BING_MIN_INTERVAL - (now - _bing_last_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _bing_last_at = time.monotonic()


def _google_client_kwargs() -> dict[str, Any]:
    client_kwargs: dict[str, Any] = {"timeout": _HTTP_TIMEOUT}
    proxy = _google_proxy_url()
    if proxy:
        client_kwargs["proxy"] = proxy
    return client_kwargs


async def _translate_google_gtx(text: str, target: str) -> str | None:
    query = f"client=gtx&sl=auto&tl={quote(target)}&dt=t&q={quote(text)}"
    client_kwargs = _google_client_kwargs()
    last_err: Exception | None = None

    for base_url in _GOOGLE_BASE_URLS:
        url = f"{base_url}?{query}"
        for attempt in range(1, _GOOGLE_MAX_ATTEMPTS + 1):
            await _google_throttle()
            resp: httpx.Response | None = None
            try:
                async with httpx.AsyncClient(**client_kwargs) as client:
                    resp = await client.get(url, headers=_GOOGLE_HEADERS)
            except httpx.HTTPError as exc:
                last_err = exc
                if attempt < _GOOGLE_MAX_ATTEMPTS:
                    await asyncio.sleep(_retry_delay_seconds(attempt, 0, resp))
                    continue
                break

            if resp.status_code in _RETRYABLE_STATUS:
                last_err = RuntimeError(f"HTTP {resp.status_code}")
                if attempt < _GOOGLE_MAX_ATTEMPTS:
                    delay = _retry_delay_seconds(attempt, resp.status_code, resp)
                    logger.info(
                        "google translate retry %s/%s: HTTP %s (wait %.1fs)",
                        attempt,
                        _GOOGLE_MAX_ATTEMPTS,
                        resp.status_code,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                break

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

    logger.warning("google translate failed: %s", last_err)
    return None


async def _translate_bing(text: str, target: str) -> str | None:
    """Free Edge translate via translatetext (no auth token; auth endpoint retired)."""
    to_lang = _map_target_for_bing(target)
    url = f"{_EDGE_TRANSLATE_TEXT_URL}?isEnterpriseClient=false&to={quote(to_lang)}"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": _EDGE_UA,
    }
    body = [text]
    last_err: Exception | None = None

    for attempt in range(1, _BING_MAX_ATTEMPTS + 1):
        await _bing_throttle()
        resp: httpx.Response | None = None
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.post(url, headers=headers, json=body)
        except httpx.HTTPError as exc:
            last_err = exc
            if attempt < _BING_MAX_ATTEMPTS:
                await asyncio.sleep(_retry_delay_seconds(attempt, 0, resp))
                continue
            break

        if resp.status_code in _RETRYABLE_STATUS:
            last_err = RuntimeError(f"HTTP {resp.status_code}")
            if attempt < _BING_MAX_ATTEMPTS:
                delay = _retry_delay_seconds(attempt, resp.status_code, resp)
                logger.info(
                    "bing translate retry %s/%s: HTTP %s (wait %.1fs)",
                    attempt,
                    _BING_MAX_ATTEMPTS,
                    resp.status_code,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            break

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

    logger.warning("bing translate failed: %s", last_err)
    return None


async def _translate_deepl(text: str, target: str) -> str | None:
    url = _deepl_translate_url()
    mode = _deepl_api_mode(url)
    api_key = _deepl_api_key()
    if mode == "official" and not api_key:
        logger.warning("deepl translate skipped: API key not configured")
        return None
    if mode == "deeplx" and not url:
        logger.warning("deepl translate skipped: DeepLX API URL not configured")
        return None

    target_lang = _map_target_for_deepl(target)
    client_kwargs = _deepl_client_kwargs()
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if mode == "official":
        headers["Authorization"] = f"DeepL-Auth-Key {api_key}"
        body: dict[str, Any] = {"text": [text], "target_lang": target_lang}
    else:
        body = {"text": text, "target_lang": target_lang}

    last_err: Exception | None = None

    for attempt in range(1, _DEEPL_MAX_ATTEMPTS + 1):
        await _deepl_throttle()
        resp: httpx.Response | None = None
        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                resp = await client.post(url, headers=headers, json=body)
        except httpx.HTTPError as exc:
            last_err = exc
            if attempt < _DEEPL_MAX_ATTEMPTS:
                await asyncio.sleep(_retry_delay_seconds(attempt, 0, resp))
                continue
            break

        if resp.status_code in _RETRYABLE_STATUS:
            last_err = RuntimeError(f"HTTP {resp.status_code}")
            if attempt < _DEEPL_MAX_ATTEMPTS:
                delay = _retry_delay_seconds(attempt, resp.status_code, resp)
                logger.info(
                    "deepl translate retry %s/%s: HTTP %s (wait %.1fs)",
                    attempt,
                    _DEEPL_MAX_ATTEMPTS,
                    resp.status_code,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            break

        if not resp.is_success:
            last_err = RuntimeError(f"HTTP {resp.status_code}")
            break

        try:
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            break

        if mode == "deeplx" and isinstance(data, dict) and data.get("code") in (429, "429"):
            last_err = RuntimeError("DeepLX rate limited (code 429)")
            if attempt < _DEEPL_MAX_ATTEMPTS:
                delay = _retry_delay_seconds(attempt, 429, resp)
                logger.info(
                    "deepl translate retry %s/%s: DeepLX 429 (wait %.1fs)",
                    attempt,
                    _DEEPL_MAX_ATTEMPTS,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            break

        translated = _parse_deeplx(data) if mode == "deeplx" else _parse_deepl(data)
        if translated:
            return translated
        if isinstance(data, dict) and data.get("message"):
            last_err = RuntimeError(str(data.get("message")))
        else:
            last_err = RuntimeError("empty deepl parse")
        break

    logger.warning("deepl translate failed: %s", last_err)
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
    elif provider == "deepl":
        translated = await _translate_deepl(s, target)
        if not translated:
            logger.info("deepl translate unavailable, trying bing fallback")
            translated = await _translate_bing(s, target)
    else:
        translated = await _translate_google_gtx(s, target)
        if not translated:
            logger.info("google translate unavailable, trying bing fallback")
            translated = await _translate_bing(s, target)

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
