from app.config import Settings
from app.services.images import site_proxy_url, validate_proxy_url
from app.services.metatube import MetaTubeClient
import pytest


def test_primary_image_url_encodes_source():
    client = MetaTubeClient(Settings(metatube_base_url="https://mt.example", metatube_token="t"))
    url = client.primary_image_url(
        "JavBus",
        "IPX-236",
        url="https://www.javbus.com/pics/cover/6uzt_b.jpg",
        quality=90,
    )
    assert url.startswith("https://mt.example/v1/images/primary/JavBus/IPX-236?")
    assert "url=" in url
    assert "quality=90" in url


def test_site_proxy_url_rewrites_cdn():
    raw = "https://www.javbus.com/pics/cover/83ie_b.jpg"
    out = site_proxy_url(raw)
    assert out is not None
    assert out.startswith("/api/images/proxy?url=")
    assert "javbus.com" in out


def test_site_proxy_url_idempotent():
    existing = "/api/images/proxy?url=https%3A%2F%2Fx.com%2Fa.jpg"
    assert site_proxy_url(existing) == existing


def test_proxied_image_url_uses_site_proxy():
    client = MetaTubeClient(Settings(metatube_base_url="https://mt.example", metatube_token="t"))
    raw = "https://www.javbus.com/pics/cover/x.jpg"
    out = client.proxied_image_url(None, None, raw)
    assert out and out.startswith("/api/images/proxy?url=")
    assert client.proxied_image_url("JavBus", "id", None) is None


def test_validate_proxy_blocks_localhost():
    with pytest.raises(ValueError):
        validate_proxy_url("http://127.0.0.1/x")
    with pytest.raises(ValueError):
        validate_proxy_url("http://localhost/secret")
    assert validate_proxy_url("https://cdn.example.com/a.jpg").startswith("https://")
