from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from app.config import get_settings
from app.services.images import (
    disk_cache_get,
    disk_cache_set,
    external_proxy_url,
    rewrite_image_url,
    site_proxy_url,
)


def test_external_proxy_url_replaces_placeholder():
    raw = "https://cdn.example.com/a.jpg"
    out = external_proxy_url(raw, "https://wsrv.nl/?url={url}")
    assert out == f"https://wsrv.nl/?url={quote(raw, safe='')}"


def test_external_proxy_url_requires_placeholder():
    assert external_proxy_url("https://x.com/a.jpg", "https://proxy.example/") is None
    assert external_proxy_url("https://x.com/a.jpg", "") is None


def test_rewrite_image_url_external_mode(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "image_proxy_mode", "external")
    monkeypatch.setattr(s, "image_external_proxy_url", "https://img.example.com/p?u={url}")
    raw = "https://cdn.example.com/cover.jpg"
    out = rewrite_image_url(raw, provider="JavBus", provider_id="IPX-1")
    assert out == f"https://img.example.com/p?u={quote(raw, safe='')}"


def test_rewrite_image_url_external_fallback_without_template(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "image_proxy_mode", "external")
    monkeypatch.setattr(s, "image_external_proxy_url", "")
    raw = "https://cdn.example.com/cover.jpg"
    out = rewrite_image_url(raw)
    assert out == site_proxy_url(raw)


def test_rewrite_image_url_local_cache_does_not_force_site(monkeypatch):
    """Local cache only affects /api/images/proxy; rewrite mode stays independent."""
    s = get_settings()
    monkeypatch.setattr(s, "image_local_cache", True)
    monkeypatch.setattr(s, "image_proxy_mode", "site")
    raw = "https://cdn.example.com/a.jpg"
    assert rewrite_image_url(raw, provider="JavBus", provider_id="x").startswith(
        "/api/images/proxy?url="
    )

    monkeypatch.setattr(s, "image_proxy_mode", "metatube")
    monkeypatch.setattr(s, "metatube_base_url", "https://mt.example")
    out = rewrite_image_url(raw, provider="JavBus", provider_id="IPX-1")
    assert out and out.startswith("https://mt.example/v1/images/primary/JavBus/IPX-1?")


def _patch_cache_settings(monkeypatch, cache_root: Path, max_mb: int = 64):
    class _S:
        image_local_cache = True
        image_cache_max_mb = max_mb

        @property
        def image_cache_path(self) -> Path:
            return cache_root

    # disk helpers import get_settings inside the function from app.config
    monkeypatch.setattr("app.config.get_settings", lambda: _S())


def test_disk_cache_roundtrip(monkeypatch, tmp_path: Path):
    cache_root = tmp_path / "image-cache"
    _patch_cache_settings(monkeypatch, cache_root)
    url = "https://cdn.example.com/poster.jpg"
    body = b"\xff\xd8\xff fake-jpeg"
    disk_cache_set(url, "image/jpeg", body)
    got = disk_cache_get(url)
    assert got is not None
    ctype, data = got
    assert ctype == "image/jpeg"
    assert data == body
    # files exist under hash prefix
    assert any(cache_root.rglob("*"))


def test_disk_cache_miss(monkeypatch, tmp_path: Path):
    _patch_cache_settings(monkeypatch, tmp_path / "empty-cache")
    assert disk_cache_get("https://cdn.example.com/missing.jpg") is None
