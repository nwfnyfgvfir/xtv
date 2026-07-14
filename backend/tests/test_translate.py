import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.translate import (
    _map_target_for_bing,
    _parse_bing,
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

    settings = SimpleNamespace(translate_provider="google")

    async def run():
        with (
            patch("app.services.translate.get_settings", return_value=settings),
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            return await translate_text("原タイトルです")

    out = asyncio.run(run())
    assert out == "译后标题"
    mock_client.get.assert_awaited()


def test_translate_bing_mock():
    auth_resp = MagicMock()
    auth_resp.status_code = 200
    auth_resp.is_success = True
    # dummy three-segment token (exp parse may fail → fallback TTL ok)
    auth_resp.text = "aaa.bbb.ccc"

    translate_resp = MagicMock()
    translate_resp.status_code = 200
    translate_resp.is_success = True
    translate_resp.json.return_value = [
        {"translations": [{"text": "译后标题", "to": "zh-Hans"}]}
    ]

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.get = AsyncMock(return_value=auth_resp)
    mock_client.post = AsyncMock(return_value=translate_resp)

    settings = SimpleNamespace(translate_provider="bing")

    async def run():
        with (
            patch("app.services.translate.get_settings", return_value=settings),
            patch("app.services.translate._edge_token", None),
            patch("app.services.translate._edge_token_exp", 0.0),
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            return await translate_text("原タイトルです")

    out = asyncio.run(run())
    assert out == "译后标题"
    mock_client.get.assert_awaited()
    mock_client.post.assert_awaited()
    call_kwargs = mock_client.post.await_args
    assert "api-version=3.0" in call_kwargs.args[0]
    assert "to=zh-Hans" in call_kwargs.args[0]
    headers = call_kwargs.kwargs.get("headers") or {}
    assert headers.get("Authorization") == "Bearer aaa.bbb.ccc"
    assert call_kwargs.kwargs.get("json") == [{"Text": "原タイトルです"}]


def test_translate_bing_401_refreshes_token():
    auth_resp = MagicMock()
    auth_resp.status_code = 200
    auth_resp.is_success = True
    auth_resp.text = "tok.a.b"

    unauthorized = MagicMock()
    unauthorized.status_code = 401
    unauthorized.is_success = False

    ok_resp = MagicMock()
    ok_resp.status_code = 200
    ok_resp.is_success = True
    ok_resp.json.return_value = [{"translations": [{"text": "成功", "to": "zh-Hans"}]}]

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.get = AsyncMock(return_value=auth_resp)
    mock_client.post = AsyncMock(side_effect=[unauthorized, ok_resp])

    settings = SimpleNamespace(translate_provider="bing")

    async def run():
        with (
            patch("app.services.translate.get_settings", return_value=settings),
            patch("app.services.translate._edge_token", None),
            patch("app.services.translate._edge_token_exp", 0.0),
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("app.services.translate.asyncio.sleep", new_callable=AsyncMock),
        ):
            return await translate_text("hello world title")

    out = asyncio.run(run())
    assert out == "成功"
    assert mock_client.get.await_count >= 2
    assert mock_client.post.await_count == 2
