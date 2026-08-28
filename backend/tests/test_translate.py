import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.translate import (
    _map_target_for_bing,
    _map_target_for_deepl,
    _parse_bing,
    _parse_deepl,
    _parse_gtx,
    looks_chinese,
    translate_text,
)


def test_looks_chinese_true():
    assert looks_chinese("这是中文标题")
    assert looks_chinese("中文字幕")


def test_looks_chinese_false_for_japanese():
    assert not looks_chinese("これは日本語のタイトルです")
    assert not looks_chinese("SSIS-001")


def test_parse_gtx():
    data = [[["你好", "hello", None, None, 10]], None, "en"]
    assert _parse_gtx(data) == "你好"


def test_parse_bing():
    data = [{"translations": [{"text": "你好", "to": "zh-Hans"}], "detectedLanguage": {"language": "en", "score": 1.0}}]
    assert _parse_bing(data) == "你好"
    assert _parse_bing([]) is None
    assert _parse_bing([{"translations": []}]) is None
    assert _parse_bing("bad") is None


def test_map_target_for_bing():
    assert _map_target_for_bing("zh-CN") == "zh-Hans"
    assert _map_target_for_bing("zh") == "zh-Hans"
    assert _map_target_for_bing("zh-TW") == "zh-Hant"
    assert _map_target_for_bing("en") == "en"


def test_map_target_for_deepl():
    assert _map_target_for_deepl("zh-CN") == "ZH"
    assert _map_target_for_deepl("zh") == "ZH"
    assert _map_target_for_deepl("zh-TW") == "ZH-HANT"
    assert _map_target_for_deepl("zh-Hant") == "ZH-HANT"


def test_parse_deepl():
    data = {"translations": [{"detected_source_language": "JA", "text": "你好"}]}
    assert _parse_deepl(data) == "你好"
    assert _parse_deepl({}) is None
    assert _parse_deepl({"translations": []}) is None


def test_parse_deeplx():
    from app.services.translate import _parse_deeplx

    data = {"code": 200, "data": "你好", "target_lang": "ZH"}
    assert _parse_deeplx(data) == "你好"
    assert _parse_deeplx({"code": 400, "message": "bad"}) is None


def test_translate_skip_chinese():
    async def run():
        return await translate_text("已经是中文")

    out = asyncio.run(run())
    assert out == "已经是中文"


def test_translate_gtx_mock():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.is_success = True
    mock_resp.json.return_value = [[["译后标题", "原标题", None, None, 10]]]

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.get = AsyncMock(return_value=mock_resp)

    settings = SimpleNamespace(
        translate_provider="google",
        translate_google_proxy=False,
        translate_google_proxy_url="",
    )

    async def run():
        with (
            patch("app.services.translate.get_settings", return_value=settings),
            patch("httpx.AsyncClient", return_value=mock_client) as client_ctor,
            patch("app.services.translate._google_throttle", new_callable=AsyncMock),
        ):
            out = await translate_text("原タイトルです")
            client_ctor.assert_called()
            assert "proxy" not in (client_ctor.call_args.kwargs or {})
            return out

    out = asyncio.run(run())
    assert out == "译后标题"
    mock_client.get.assert_awaited()


def test_translate_gtx_uses_proxy_when_enabled():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.is_success = True
    mock_resp.json.return_value = [[["译后", "原", None, None, 10]]]

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.get = AsyncMock(return_value=mock_resp)

    settings = SimpleNamespace(
        translate_provider="google",
        translate_google_proxy=True,
        translate_google_proxy_url="http://127.0.0.1:7890",
    )

    async def run():
        with (
            patch("app.services.translate.get_settings", return_value=settings),
            patch("httpx.AsyncClient", return_value=mock_client) as client_ctor,
            patch("app.services.translate._google_throttle", new_callable=AsyncMock),
        ):
            out = await translate_text("これは日本語")
            kwargs = client_ctor.call_args.kwargs or {}
            assert kwargs.get("proxy") == "http://127.0.0.1:7890"
            return out

    out = asyncio.run(run())
    assert out == "译后"


def test_translate_gtx_proxy_off_ignores_url():
    from app.services.translate import _google_proxy_url

    settings = SimpleNamespace(
        translate_google_proxy=False,
        translate_google_proxy_url="http://127.0.0.1:7890",
    )
    with patch("app.services.translate.get_settings", return_value=settings):
        assert _google_proxy_url() is None


def test_translate_google_falls_back_to_bing():
    from app.services.translate import _CACHE, _CACHE_LOCK

    with _CACHE_LOCK:
        _CACHE.clear()

    rate_limited = MagicMock()
    rate_limited.status_code = 429
    rate_limited.is_success = False
    rate_limited.headers = {}

    bing_ok = MagicMock()
    bing_ok.status_code = 200
    bing_ok.is_success = True
    bing_ok.json.return_value = [{"translations": [{"text": "必应译", "to": "zh-Hans"}]}]

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.get = AsyncMock(return_value=rate_limited)
    mock_client.post = AsyncMock(return_value=bing_ok)

    settings = SimpleNamespace(
        translate_provider="google",
        translate_google_proxy=False,
        translate_google_proxy_url="",
    )

    async def run():
        with (
            patch("app.services.translate.get_settings", return_value=settings),
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("app.services.translate.asyncio.sleep", new_callable=AsyncMock),
            patch("app.services.translate._google_throttle", new_callable=AsyncMock),
            patch("app.services.translate._bing_throttle", new_callable=AsyncMock),
        ):
            return await translate_text("fallback-only-phrase")

    out = asyncio.run(run())
    assert out == "必应译"
    mock_client.post.assert_awaited()


def test_normalize_deepl_api_url():
    from app.services.translate import _normalize_deepl_api_url

    assert _normalize_deepl_api_url("") == ""
    assert (
        _normalize_deepl_api_url("https://api-free.deepl.com/v2/translate")
        == "https://api-free.deepl.com/v2/translate"
    )
    assert (
        _normalize_deepl_api_url("https://proxy.example.com/deepl")
        == "https://proxy.example.com/deepl/v2/translate"
    )
    assert (
        _normalize_deepl_api_url(
            "https://api.deeplx.org/token123/translate"
        )
        == "https://api.deeplx.org/token123/translate"
    )


def test_deepl_api_mode():
    from app.services.translate import _deepl_api_mode

    assert _deepl_api_mode("https://api-free.deepl.com/v2/translate") == "official"
    assert _deepl_api_mode("https://api.deeplx.org/abc/translate") == "deeplx"
    assert _deepl_api_mode("https://api.deeplx.org/translate") == "deeplx"


def test_deepl_custom_api_url():
    from app.services.translate import _deepl_translate_url

    settings = SimpleNamespace(
        translate_deepl_api_url="https://proxy.example.com/deepl/",
        translate_deepl_free=True,
        translate_deepl_api_key="key:fx",
    )
    with patch("app.services.translate.get_settings", return_value=settings):
        assert _deepl_translate_url() == "https://proxy.example.com/deepl/v2/translate"


def test_translate_deeplx_mock():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.is_success = True
    mock_resp.json.return_value = {
        "code": 200,
        "data": "DeepLX译",
        "target_lang": "ZH",
    }

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post = AsyncMock(return_value=mock_resp)

    settings = SimpleNamespace(
        translate_provider="deepl",
        translate_deepl_api_key="token123",
        translate_deepl_api_url="https://api.deeplx.org/token123/translate",
        translate_deepl_free=True,
        translate_deepl_proxy=False,
        translate_deepl_proxy_url="",
    )

    async def run():
        with (
            patch("app.services.translate.get_settings", return_value=settings),
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("app.services.translate._deepl_throttle", new_callable=AsyncMock),
        ):
            return await translate_text("これは日本語 deeplx")

    out = asyncio.run(run())
    assert out == "DeepLX译"
    call_kwargs = mock_client.post.await_args.kwargs
    assert call_kwargs["json"]["text"] == "これは日本語 deeplx"
    assert call_kwargs["json"]["target_lang"] == "ZH"
    assert "Authorization" not in (call_kwargs.get("headers") or {})
    assert (
        mock_client.post.await_args.args[0]
        == "https://api.deeplx.org/token123/translate"
    )


def test_translate_deepl_mock():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.is_success = True
    mock_resp.json.return_value = {
        "translations": [{"detected_source_language": "JA", "text": "DeepL译"}]
    }

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post = AsyncMock(return_value=mock_resp)

    settings = SimpleNamespace(
        translate_provider="deepl",
        translate_deepl_api_key="test-key:fx",
        translate_deepl_api_url="https://custom.example.com/v2/translate",
        translate_deepl_free=True,
        translate_deepl_proxy=False,
        translate_deepl_proxy_url="",
    )

    async def run():
        with (
            patch("app.services.translate.get_settings", return_value=settings),
            patch("httpx.AsyncClient", return_value=mock_client) as client_ctor,
            patch("app.services.translate._deepl_throttle", new_callable=AsyncMock),
        ):
            out = await translate_text("これは日本語")
            kwargs = client_ctor.call_args.kwargs or {}
            assert "proxy" not in kwargs
            return out

    out = asyncio.run(run())
    assert out == "DeepL译"
    assert mock_client.post.await_args.args[0] == "https://custom.example.com/v2/translate"
    call_kwargs = mock_client.post.await_args.kwargs
    assert call_kwargs["json"]["target_lang"] == "ZH"
    assert call_kwargs["headers"]["Authorization"] == "DeepL-Auth-Key test-key:fx"


def test_translate_deepl_uses_proxy():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.is_success = True
    mock_resp.json.return_value = {
        "translations": [{"detected_source_language": "JA", "text": "代理译"}]
    }

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post = AsyncMock(return_value=mock_resp)

    settings = SimpleNamespace(
        translate_provider="deepl",
        translate_deepl_api_key="pro-key",
        translate_deepl_free=False,
        translate_deepl_proxy=True,
        translate_deepl_proxy_url="socks5h://127.0.0.1:1080",
    )

    async def run():
        with (
            patch("app.services.translate.get_settings", return_value=settings),
            patch("httpx.AsyncClient", return_value=mock_client) as client_ctor,
            patch("app.services.translate._deepl_throttle", new_callable=AsyncMock),
        ):
            out = await translate_text("proxy phrase")
            kwargs = client_ctor.call_args.kwargs or {}
            assert kwargs.get("proxy") == "socks5h://127.0.0.1:1080"
            return out

    out = asyncio.run(run())
    assert out == "代理译"


def test_translate_deeplx_retries_429():
    from app.services.translate import _CACHE, _CACHE_LOCK

    with _CACHE_LOCK:
        _CACHE.clear()

    rate_limited = MagicMock()
    rate_limited.status_code = 429
    rate_limited.is_success = False
    rate_limited.headers = {}

    ok_resp = MagicMock()
    ok_resp.status_code = 200
    ok_resp.is_success = True
    ok_resp.json.return_value = {"code": 200, "data": "重试成功"}

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post = AsyncMock(side_effect=[rate_limited, ok_resp])

    settings = SimpleNamespace(
        translate_provider="deepl",
        translate_deepl_api_key="token123",
        translate_deepl_api_url="https://api.deeplx.org/token123/translate",
        translate_deepl_free=True,
        translate_deepl_proxy=False,
        translate_deepl_proxy_url="",
    )

    async def run():
        with (
            patch("app.services.translate.get_settings", return_value=settings),
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("app.services.translate._deepl_throttle", new_callable=AsyncMock),
            patch("app.services.translate.asyncio.sleep", new_callable=AsyncMock),
        ):
            return await translate_text("deeplx-429-retry")

    out = asyncio.run(run())
    assert out == "重试成功"
    assert mock_client.post.await_count == 2


def test_translate_bing_mock():
    translate_resp = MagicMock()
    translate_resp.status_code = 200
    translate_resp.is_success = True
    translate_resp.json.return_value = [
        {"translations": [{"text": "译后标题", "to": "zh-Hans"}]}
    ]

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post = AsyncMock(return_value=translate_resp)

    settings = SimpleNamespace(translate_provider="bing")

    async def run():
        with (
            patch("app.services.translate.get_settings", return_value=settings),
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("app.services.translate._bing_throttle", new_callable=AsyncMock),
        ):
            return await translate_text("原タイトルです")

    out = asyncio.run(run())
    assert out == "译后标题"
    mock_client.post.assert_awaited()
    call_kwargs = mock_client.post.await_args
    assert "translatetext" in call_kwargs.args[0]
    assert "to=zh-Hans" in call_kwargs.args[0]
    assert call_kwargs.kwargs.get("json") == ["原タイトルです"]
    headers = call_kwargs.kwargs.get("headers") or {}
    assert "Authorization" not in headers


def test_translate_bing_retries_429():
    from app.services.translate import _CACHE, _CACHE_LOCK

    with _CACHE_LOCK:
        _CACHE.clear()

    rate_limited = MagicMock()
    rate_limited.status_code = 429
    rate_limited.is_success = False
    rate_limited.headers = {}

    ok_resp = MagicMock()
    ok_resp.status_code = 200
    ok_resp.is_success = True
    ok_resp.json.return_value = [{"translations": [{"text": "成功", "to": "zh-Hans"}]}]

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post = AsyncMock(side_effect=[rate_limited, ok_resp])

    settings = SimpleNamespace(translate_provider="bing")

    async def run():
        with (
            patch("app.services.translate.get_settings", return_value=settings),
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("app.services.translate._bing_throttle", new_callable=AsyncMock),
            patch("app.services.translate.asyncio.sleep", new_callable=AsyncMock),
        ):
            return await translate_text("hello world title bing429")

    out = asyncio.run(run())
    assert out == "成功"
    assert mock_client.post.await_count == 2
