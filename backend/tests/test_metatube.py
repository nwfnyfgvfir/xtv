from app.config import Settings
from app.services.metatube import MetaTubeClient


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


def test_proxied_image_url_skips_already_proxied():
    client = MetaTubeClient(Settings(metatube_base_url="https://mt.example", metatube_token="t"))
    existing = "https://mt.example/v1/images/primary/JavBus/SSIS-001?url=x"
    assert client.proxied_image_url("JavBus", "SSIS-001", existing) == existing


def test_proxied_image_url_rewrites_source_cdn():
    client = MetaTubeClient(Settings(metatube_base_url="https://mt.example", metatube_token="t"))
    raw = "https://www.javbus.com/pics/cover/83ie_b.jpg"
    out = client.proxied_image_url("JavBus", "SSIS-001", raw)
    assert out is not None
    assert out.startswith("https://mt.example/v1/images/primary/JavBus/SSIS-001?")
    assert "javbus.com" in out


def test_proxied_image_url_without_provider_keeps_raw():
    client = MetaTubeClient(Settings(metatube_base_url="https://mt.example", metatube_token="t"))
    raw = "https://www.javbus.com/pics/cover/x.jpg"
    assert client.proxied_image_url(None, None, raw) == raw
    assert client.proxied_image_url("JavBus", None, raw) == raw
    assert client.proxied_image_url(None, "id", raw) == raw
    assert client.proxied_image_url("JavBus", "id", None) is None
