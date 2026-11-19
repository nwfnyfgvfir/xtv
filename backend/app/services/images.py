from __future__ import annotations

import base64
import binascii
import hashlib
import ipaddress
import logging
import re
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path
from threading import Lock
from time import time
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse, urlsplit

import httpx

logger = logging.getLogger(__name__)

# Simple in-memory LRU cache: url -> (expires_at, content_type, body)
_CACHE: OrderedDict[str, tuple[float, str, bytes]] = OrderedDict()
_CACHE_LOCK = Lock()
_CACHE_MAX = 256
_CACHE_TTL = 3600.0
_DISK_LOCK = Lock()
MAX_IMAGE_BYTES = 5 * 1024 * 1024
_SCRAPED_IMAGE_EXTENSIONS = {
    "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
    "image/gif": "gif", "image/avif": "avif",
}
_PROXY_TEMPLATE_FIELDS = frozenset({'url', 'provider', 'id', 'quality'})


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
    if not extension or len(encoded) > ((MAX_IMAGE_BYTES + 2) // 3) * 4:
        return None
    try:
        body = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        return None
    if not body or len(body) > MAX_IMAGE_BYTES:
        return None
    return store_image_bytes(body)


def store_image_bytes(body: bytes) -> str | None:
    """Store inline artwork and remote backups in the same content-addressed store."""
    if not body or len(body) > MAX_IMAGE_BYTES:
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
            if not path.is_file() or path.stat().st_size != len(body) or path.read_bytes() != body:
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


def normalize_site_image_base_url(value: str) -> str:
    """Validate a browser-facing image origin, optionally with a proxy path prefix."""
    if not value.strip():
        return ''
    base = value.strip().rstrip('/')
    error = '本站图片访问地址须为 HTTP(S) 基础地址，可包含部署子路径；不能包含账号、查询参数或片段'
    try:
        parsed = urlsplit(base)
        _ = parsed.port
        if (parsed.scheme not in {'http', 'https'} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or '?' in base or '#' in base or re.search(r'[\x00-\x20\x7f\\]', base)):
            raise ValueError(error)
        path = unquote(parsed.path)
        if ('\\' in path or '//' in path or any(part in {'.', '..'} for part in path.split('/'))
                or re.search(r'[\x00-\x20\x7f]', path)):
            raise ValueError(error)
        if '/api/images' in path:
            raise ValueError('本站图片访问地址请填写基础地址，不要填写 /api/images 图片接口路径')
    except ValueError as exc:
        if str(exc).startswith('本站图片访问地址'):
            raise
        raise ValueError(error) from exc
    return base


def site_image_path(url: str) -> str | None:
    """Recognize only TV image resources, including URLs published on the image host."""
    from app.config import get_settings

    try:
        parsed = urlsplit(url)
        path = parsed.path
        if parsed.scheme or parsed.netloc:
            base = getattr(get_settings(), 'image_site_base_url', '').strip().rstrip('/')
            if not base:
                return None
            origin = urlsplit(base)
            if (parsed.scheme.lower(), parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80)) != (
                    origin.scheme.lower(), origin.hostname, origin.port or (443 if origin.scheme == 'https' else 80)):
                return None
            prefix = origin.path.rstrip('/')
            if not path.startswith(prefix + '/'):
                return None
            path = path[len(prefix):]
        if path == '/api/images/proxy' or path.startswith('/api/images/scraped/'):
            return path + ('?' + parsed.query if parsed.query else '')
    except ValueError:
        pass
    return None


def site_image_url(url: str | None) -> str | None:
    """Publish canonical image paths without ever changing their stored location."""
    if not url:
        return url
    path = site_image_path(url)
    if path is None:
        return url
    from app.config import get_settings

    base = getattr(get_settings(), 'image_site_base_url', '').strip().rstrip('/')
    return base + path


def original_image_url(url: str | None) -> str | None:
    """Unwrap known proxy URLs so a saved proxy choice never locks in an old route."""
    if not url:
        return url
    from app.config import get_settings

    settings = get_settings()
    current = 'https:' + url if url.startswith('//') else url
    template = (getattr(settings, 'image_external_proxy_url', '') or '').strip()
    for _ in range(8):
        current = site_image_path(current) or current
        try:
            parsed = urlsplit(current)
        except ValueError:
            return current
        inner = None
        if not parsed.scheme and not parsed.netloc and parsed.path == '/api/images/proxy':
            inner = next(iter(parse_qs(parsed.query).get('url', [])), None)
        elif template and not remote_proxy_template_error(template):
            match = _proxy_template_pattern(template).fullmatch(current)
            if match:
                inner = unquote(match.group('url'))
        if not inner or not inner.startswith(('http://', 'https://', '/api/images/proxy?')) or inner == current:
            return current
        current = inner
    return None


def site_proxy_url(url: str | None) -> str | None:
    """Publish the site proxy on the configured image host, or the current origin."""
    if not url:
        return url
    if path := site_image_path(url):
        return site_image_url(path)
    # Already relative site path
    if url.startswith("/") and not url.startswith("//"):
        return url
    if not (url.startswith("http://") or url.startswith("https://")):
        return url
    return site_image_url(f"/api/images/proxy?url={quote(url, safe='')}")


def remote_proxy_template_error(template: str) -> str | None:
    tpl = (template or "").strip()
    if not tpl or "{url}" not in tpl:
        return '远程图片代理模板必须包含 {url}'
    fields = re.findall(r'\{([^{}]*)\}', tpl)
    remainder = re.sub(r'\{[^{}]*\}', '', tpl)
    if set(fields) - _PROXY_TEMPLATE_FIELDS or '{' in remainder or '}' in remainder:
        return '图片代理模板仅支持 {url}、{provider}、{id} 和 {quality}'
    try:
        parsed = urlsplit(tpl)
        _ = parsed.port
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or '{' in parsed.netloc or '}' in parsed.netloc or re.search(r'[\x00-\x20]', tpl):
            return '远程图片代理模板必须是有效的 HTTP(S) 地址，变量应位于路径或查询参数中'
    except ValueError:
        return '远程图片代理模板不是有效的 HTTP(S) 地址'
    return None


@lru_cache(maxsize=32)
def _proxy_template_pattern(template: str) -> re.Pattern:
    """Recognize the original URL in the same template used to render the proxy URL."""
    parts, seen_url = [], False
    for part in re.split(r'(\{(?:url|provider|id|quality)\})', template):
        if part == '{url}':
            parts.append('(?P=url)' if seen_url else '(?P<url>.+?)')
            seen_url = True
        elif part in {'{provider}', '{id}'}:
            parts.append('[^/?&#]+')
        elif part == '{quality}':
            parts.append('[0-9]+')
        else:
            parts.append(re.escape(part))
    return re.compile(''.join(parts))


def remote_proxy_url(url: str, template: str, *, provider: str | None = None,
    provider_id: str | None = None, quality: int = 90) -> str | None:
    """Render all remote proxies, including MetaTube, using one template policy."""
    if remote_proxy_template_error(template):
        return None
    tpl = template.strip()
    if (('{provider}' in tpl and not provider) or ('{id}' in tpl and not provider_id)
            or (provider and provider.startswith('stash:') and ('{provider}' in tpl or '{id}' in tpl))):
        return url
    values = {'url': url, 'provider': provider or '', 'id': provider_id or '', 'quality': str(quality)}
    return re.sub(r'\{(url|provider|id|quality)\}',
        lambda match: quote(str(values[match.group(1)]), safe=''), tpl)


def rewrite_image_url(
    url: str | None,
    *,
    provider: str | None = None,
    provider_id: str | None = None,
    quality: int = 90,
) -> str | None:
    """Select the site proxy or the shared remote template, preserving local artwork."""
    url = original_image_url(url)
    if not url:
        return url
    # Inline-only artwork has no remote URL to hand to another service.
    if url.startswith("/") and not url.startswith("//"):
        return site_image_url(url)
    if not (url.startswith("http://") or url.startswith("https://")):
        return url

    from app.config import get_settings

    s = get_settings()
    mode = (s.image_proxy_mode or "site").strip().lower()

    if mode == "external":
        out = remote_proxy_url(url, s.image_external_proxy_url,
            provider=provider, provider_id=provider_id, quality=quality)
        if out:
            return out
        logger.warning("Remote image proxy configuration is invalid; no site proxy fallback is used")
        return None

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


async def fetch_image(url: str, *, referer_url: str | None = None) -> tuple[str, bytes]:
    """Fetch bounded image bytes with identical validation for proxying and backups."""
    source = urlsplit(referer_url or url)
    headers = {'User-Agent': 'Mozilla/5.0 TV-Images', 'Accept': 'image/*',
        'Referer': f'{source.scheme}://{source.netloc}/'}
    async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=10), follow_redirects=False) as client:
        for _ in range(6):
            validate_proxy_url(url)
            async with client.stream('GET', url, headers=headers) as response:
                if response.is_redirect:
                    location = response.headers.get('location')
                    if not location:
                        raise ValueError('Image redirect has no location')
                    url = urljoin(url, location)
                    continue
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_IMAGE_BYTES:
                        raise ValueError('Image exceeds the size limit')
                content = bytes(body)
                content_type = image_content_type(content)
                if not content_type:
                    raise ValueError('Response is not a supported image')
                return content_type, content
    raise ValueError('Too many image redirects')


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
