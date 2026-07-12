from __future__ import annotations

import ipaddress
import re
from collections import OrderedDict
from threading import Lock
from time import time
from typing import Any
from urllib.parse import quote, urlparse

# Simple in-memory LRU cache: url -> (expires_at, content_type, body)
_CACHE: OrderedDict[str, tuple[float, str, bytes]] = OrderedDict()
_CACHE_LOCK = Lock()
_CACHE_MAX = 256
_CACHE_TTL = 3600.0


def site_proxy_url(url: str | None) -> str | None:
    """Rewrite absolute image URLs to same-origin proxy path."""
    if not url:
        return url
    if url.startswith("/api/images/proxy"):
        return url
    # Already relative site path
    if url.startswith("/") and not url.startswith("//"):
        return url
    if not (url.startswith("http://") or url.startswith("https://")):
        return url
    return f"/api/images/proxy?url={quote(url, safe='')}"


def validate_proxy_url(url: str) -> str:
    """Return normalized URL or raise ValueError (SSRF guards)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("only http/https allowed")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("missing host")
    if host in {"localhost", "metadata.google.internal"}:
        raise ValueError("blocked host")
    # Block obvious local names
    if host.endswith(".local") or host.endswith(".internal"):
        raise ValueError("blocked host")
    # IP literal checks
    try:
        ip = ipaddress.ip_address(host)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        ):
            raise ValueError("blocked ip")
    except ValueError as exc:
        if "blocked" in str(exc):
            raise
        # hostname not an IP — ok
        pass
    # Basic scheme abuse
    if re.search(r"[\x00-\x1f]", url):
        raise ValueError("invalid url")
    return url


def cache_get(url: str) -> tuple[str, bytes] | None:
    with _CACHE_LOCK:
        item = _CACHE.get(url)
        if not item:
            return None
        exp, ctype, body = item
        if exp < time():
            _CACHE.pop(url, None)
            return None
        _CACHE.move_to_end(url)
        return ctype, body


def cache_set(url: str, content_type: str, body: bytes) -> None:
    with _CACHE_LOCK:
        _CACHE[url] = (time() + _CACHE_TTL, content_type, body)
        _CACHE.move_to_end(url)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)


def proxy_cache_stats() -> dict[str, Any]:
    with _CACHE_LOCK:
        return {"entries": len(_CACHE), "max": _CACHE_MAX, "ttl": _CACHE_TTL}
