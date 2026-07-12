import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.translate import looks_chinese, _parse_gtx, translate_text


def test_looks_chinese_true():
    assert looks_chinese("这是中文标题")
    assert looks_chinese("中文字幕")


def test_looks_chinese_false_for_japanese():
    assert not looks_chinese("これは日本語のタイトルです")
    assert not looks_chinese("SSIS-001")


def test_parse_gtx():
    data = [[["你好", "hello", None, None, 10]], None, "en"]
    assert _parse_gtx(data) == "你好"


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

    async def run():
        with patch("httpx.AsyncClient", return_value=mock_client):
            return await translate_text("原タイトルです")

    out = asyncio.run(run())
    assert out == "译后标题"
