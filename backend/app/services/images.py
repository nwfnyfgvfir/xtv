from __future__ import annotations

import base64
import binascii
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
from urllib.parse import parse_qs, quote, unquote, urlparse, urlsplit

logger = logging.getLogger(__name__)

# Simple in-memory LRU cache: url -> (expires_at, content_type, body)
_CACHE: OrderedDict[str, tuple[float, str, bytes]] = OrderedDict()
_CACHE_LOCK = Lock()
_CACHE_MAX = 256
_CACHE_TTL = 3600.0
_DISK_LOCK = Lock()
_MAX_BODY = 5 * 1024 * 1024
_SCRAPED_IMAGE_EXTENSIONS = {
    "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
    "image/gif": "gif", "image/avif": "avif",
}


def image_content_type(body: bytes) -> str | None:
    """Identify image responses before serving or caching upstream error pages."""
    if body.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if body.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if body.startswith((b'GIF87a', b'GIF89a')):
        return 'image/gif'
    if body.startswith(b'RIFF') and body[8:12] == b'WEBP':
        return 'image/webp'
    if body[4:8] == b'ftyp' and any(brand in body[8:40] for brand in (b'avif', b'avis')):
        return 'image/avif'
    if body.startswith(b'BM'):
        return 'image/bmp'
    if body.startswith(b'\x00\x00\x01\x00'):
        return 'image/x-icon'
    if body.startswith((b'II\x2a\x00', b'MM\x00\x2a')):
        return 'image/tiff'
    prefix = body[:4096].lstrip(b'\xef\xbb\xbf \t\r\n')
    if re.match(rb'(?:<\?xml[^>]*\?>\s*)?(?:<!--.*?-->\s*)*(?:<!DOCTYPE\s+svg[^>]*>\s*)?<svg(?:\s|>)', prefix, re.I | re.S):
        return 'image/svg+xml'
    return None


def cache_remove(url: str) -> None:
    with _CACHE_LOCK:
        _CACHE.pop(url, None)


def scraped_image_path(name: str) -> Path | None:
    if not re.fullmatch(r"[0-9a-f]{64}\.(?:jpg|png|webp|gif|avif)", name):
        return None
    from app.config import get_settings

    return get_settings().data_dir_path / "scraped-images" / name


def store_scraped_image(value: str | None) -> str | None:
    """Persist Stash's inline raster images without embedding them in API payloads."""
    if not value:
        return None
    if value.startswith(("http://", "https://", "//", "/api/images/proxy")):
        return original_image_url(value)
    if value.startswith("/api/images/scraped/"):
        return value
    header, separator, encoded = value.partition(",")
    if not separator or not header.startswith("data:") or not header.endswith(";base64"):
        return None
    extension = _SCRAPED_IMAGE_EXTENSIONS.get(header[5:-7].lower())
    if not extension or len(encoded) > ((_MAX_BODY + 2) // 3) * 4:
        return None
    try:
        body = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        return None
    if not body or len(body) > _MAX_BODY:
        return None
    return store_image_bytes(body)


def store_image_bytes(body: bytes) -> str | None:
    """Store a bounded raster image independently of optional proxy-cache pruning."""
    if not body or len(body) > _MAX_BODY:
        return None
    extension = _SCRAPED_IMAGE_EXTENSIONS.get(image_content_type(body) or '')
    if not extension:
        return None
    name = f"{hashlib.sha256(body).hexdigest()}.{extension}"
    path = scraped_image_path(name)
    if path is None:
        return None
    try:
        with _DISK_LOCK:
            if not path.is_file():
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(".tmp")
                temporary.write_bytes(body)
                temporary.replace(path)
    except OSError:
        logger.warning("Could not save a scraped image", exc_info=True)
        return None
    return f"/api/images/scraped/{name}"


def first_scraped_image(values: list[Any]) -> str | None:
    """Keep remote artwork when available; persist inline bytes only as a fallback."""
    candidates = [value for value in values if isinstance(value, str) and value]
    for value in candidates:
        if value.startswith(("http://", "https://", "//", "/api/images/proxy")):
            original = original_image_url(value)
            if original:
                return original
    return next((image for value in candidates if (image := store_scraped_image(value))), None)


def original_image_url(url: str | None) -> str | None:
    """Unwrap known proxy URLs so a saved proxy choice never locks in an old route."""
    if not url:
        return url
    from app.config import get_settings

    settings = get_settings()
    current = 'https:' + url if url.startswith('//') else url
    template = (getattr(settings, 'image_external_proxy_url', '') or '').strip()
    for _ in range(8):
        try:
            parsed = urlsplit(current)
        except ValueError:
            return current
        inner = None
        if not parsed.scheme and not parsed.netloc and parsed.path == '/api/images/proxy':
            inner = next(iter(parse_qs(parsed.query).get('url', [])), None)
        elif getattr(settings, 'metatube_base_url', '') and current.startswith(settings.metatube_base_url.rstrip('/') + '/v1/images/primary/'):
            inner = next(iter(parse_qs(parsed.query).get('url', [])), None)
        elif template.count('{url}') == 1:
            prefix, suffix = template.split('{url}')
            if prefix and current.startswith(prefix) and (not suffix or current.endswith(suffix)):
                inner = unquote(current[len(prefix):len(current) - len(suffix) if suffix else None])
        if not inner or not inner.startswith(('http://', 'https://', '/api/images/proxy?')) or inner == current:
            return current
        current = inner
    return None


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


def external_proxy_template_error(template: str) -> str | None:
    tpl = (template or "").strip()
    if not tpl or "{url}" not in tpl:
        return '外部图片代理模板必须包含 {url}'
    try:
        parsed = urlsplit(tpl)
        _ = parsed.port
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or '{url}' in parsed.netloc or re.search(r'[\x00-\x20]', tpl):
            return '外部图片代理模板必须是有效的 HTTP(S) 地址，{url} 应位于路径或查询参数中'
    except ValueError:
        return '外部图片代理模板不是有效的 HTTP(S) 地址'
    return None


def external_proxy_url(url: str, template: str) -> str | None:
    """Build external proxy URL from a valid HTTP(S) template containing {url}."""
    if external_proxy_template_error(template):
        return None
    return template.strip().replace("{url}", quote(url, safe=""))


def rewrite_image_url(
    url: str | None,
    *,
    provider: str | None = None,
    provider_id: str | None = None,
    quality: int = 90,
) -> str | None:
    """Rewrite image URL according to IMAGE_PROXY_MODE (site | metatube | external)."""
    url = original_image_url(url)
    if not url:
        return url
    # Inline-only artwork has no remote URL to hand to another service.
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
        logger.warning("External image proxy configuration is invalid; no site proxy fallback is used")
        return None

    if mode == "metatube":
        if provider and provider_id and not provider.startswith(("stash:", "stashscrapers:")):
            from app.services.metatube import MetaTubeClient

            return MetaTubeClient().primary_image_url(
                str(provider), str(provider_id), url=url, quality=quality,
            )
        return url
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
