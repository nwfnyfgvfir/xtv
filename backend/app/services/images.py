from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import re
from collections import OrderedDict
from pathlib import Path
from threading import Lock
from time import time
from typing import Any
from urllib.parse import quote, urlparse

logger = logging.getLogger(__name__)

# Simple in-memory LRU cache: url -> (expires_at, content_type, body)
_CACHE: OrderedDict[str, tuple[float, str, bytes]] = OrderedDict()
_CACHE_LOCK = Lock()
_CACHE_MAX = 256
_CACHE_TTL = 3600.0
_DISK_LOCK = Lock()
_MAX_BODY = 5 * 1024 * 1024


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


def external_proxy_url(url: str, template: str) -> str | None:
    """Build external proxy URL from template containing {url}."""
    tpl = (template or "").strip()
    if not tpl or "{url}" not in tpl:
        return None
    return tpl.replace("{url}", quote(url, safe=""))


def rewrite_image_url(
    url: str | None,
    *,
    provider: str | None = None,
    provider_id: str | None = None,
    quality: int = 90,
) -> str | None:
    """Rewrite image URL according to IMAGE_PROXY_MODE (site | metatube | external)."""
    if not url:
        return url
    # Already proxied / relative — leave as-is
    if url.startswith("/api/images/proxy"):
        return url
    if url.startswith("/") and not url.startswith("//"):
        return url
    if not (url.startswith("http://") or url.startswith("https://")):
        return url

    from app.config import get_settings

    s = get_settings()
    mode = (s.image_proxy_mode or "site").strip().lower()

    if mode == "external":
        out = external_proxy_url(url, s.image_external_proxy_url)
        if out:
            return out
        logger.warning(
            "IMAGE_PROXY_MODE=external but IMAGE_EXTERNAL_PROXY_URL missing {url}; fallback site"
        )
        return site_proxy_url(url)

    if mode == "metatube" and provider and provider_id:
        from app.services.metatube import MetaTubeClient

        return MetaTubeClient().primary_image_url(
            str(provider),
            str(provider_id),
            url=url,
            quality=quality,
        )
    return site_proxy_url(url)


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


# ---------- disk cache (site proxy only) ----------


def ensure_image_cache_dir() -> Path:
    from app.config import get_settings

    path = get_settings().image_cache_path
    path.mkdir(parents=True, exist_ok=True)
    return path


def disk_cache_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def disk_cache_paths(url: str) -> tuple[Path, Path]:
    from app.config import get_settings

    key = disk_cache_key(url)
    root = get_settings().image_cache_path
    sub = root / key[:2]
    return sub / key, sub / f"{key}.meta"


def disk_cache_get(url: str) -> tuple[str, bytes] | None:
    body_path, meta_path = disk_cache_paths(url)
    try:
        if not body_path.is_file() or not meta_path.is_file():
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        ctype = str(meta.get("content_type") or "image/jpeg")
        body = body_path.read_bytes()
        if not body:
            return None
        return ctype, body
    except Exception:  # noqa: BLE001
        logger.debug("disk_cache_get failed for %s", url[:80], exc_info=True)
        return None


def disk_cache_set(url: str, content_type: str, body: bytes) -> None:
    if len(body) > _MAX_BODY:
        return
    with _DISK_LOCK:
        try:
            body_path, meta_path = disk_cache_paths(url)
            body_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_body = Path(str(body_path) + ".tmp")
            tmp_meta = Path(str(meta_path) + ".tmp")
            tmp_body.write_bytes(body)
            tmp_meta.write_text(
                json.dumps(
                    {
                        "content_type": content_type or "image/jpeg",
                        "url": url,
                        "saved_at": time(),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            tmp_body.replace(body_path)
            tmp_meta.replace(meta_path)
            _disk_cache_prune_if_needed()
        except Exception:  # noqa: BLE001
            logger.warning("disk_cache_set failed for %s", url[:80], exc_info=True)


def _disk_cache_prune_if_needed() -> None:
    from app.config import get_settings

    s = get_settings()
    max_mb = int(s.image_cache_max_mb or 0)
    if max_mb <= 0:
        return
    root = s.image_cache_path
    if not root.is_dir():
        return
    files: list[tuple[float, Path, int]] = []
    total = 0
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix in {".tmp"}:
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        files.append((st.st_mtime, p, st.st_size))
        total += st.st_size
    limit = max_mb * 1024 * 1024
    if total <= limit:
        return
    target = int(limit * 0.9)
    files.sort(key=lambda x: x[0])  # oldest first
    for _mtime, path, size in files:
        if total <= target:
            break
        try:
            path.unlink(missing_ok=True)
            # drop paired meta/body if present
            if path.suffix == ".meta":
                sibling = path.with_suffix("")
                if sibling.is_file():
                    sz = sibling.stat().st_size
                    sibling.unlink(missing_ok=True)
                    total -= sz
            else:
                meta = Path(str(path) + ".meta")
                if meta.is_file():
                    sz = meta.stat().st_size
                    meta.unlink(missing_ok=True)
                    total -= sz
            total -= size
        except OSError:
            continue


def disk_cache_stats() -> dict[str, Any]:
    from app.config import get_settings

    s = get_settings()
    root = s.image_cache_path
    entries = 0
    nbytes = 0
    if root.is_dir():
        for p in root.rglob("*"):
            if p.is_file() and p.suffix != ".meta" and p.suffix != ".tmp":
                entries += 1
                try:
                    nbytes += p.stat().st_size
                except OSError:
                    pass
    return {
        "enabled": bool(s.image_local_cache),
        "dir": str(root),
        "entries": entries,
        "bytes": nbytes,
        "max_mb": s.image_cache_max_mb,
    }
