import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import settings as settings_api
from app.config import Settings
from app.db import get_db
from app.deps import require_auth
from app.models import AppSetting
from app.services import translate


def completion(text="你好", **choice):
    return httpx.Response(200, json={
        "choices": [{"message": {"content": text}, "finish_reason": "stop", **choice}],
    })


@pytest.fixture
def ai_settings(monkeypatch):
    settings = Settings(
        _env_file=None,
        translate_provider="ai",
        translate_ai_api_url="https://translate.example/v1",
        translate_ai_api_key="test-key",
        translate_ai_model="test-model",
    )
    monkeypatch.setattr(translate, "get_settings", lambda: settings)
    monkeypatch.setattr(settings_api, "get_settings", lambda: settings)
    monkeypatch.setattr(translate, "_translate_bing", AsyncMock(return_value=None))
    with translate._CACHE_LOCK:
        translate._CACHE.clear()
    yield settings
    with translate._CACHE_LOCK:
        translate._CACHE.clear()


@pytest.fixture
def ai_transport(monkeypatch):
    requests = []
    responses = []

    def handler(request):
        requests.append(request)
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    client_type = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        translate.httpx, "AsyncClient",
        lambda **kwargs: client_type(transport=transport, **kwargs),
    )
    return requests, responses


@pytest.mark.parametrize(("base", "endpoint"), [
    ("https://translate.example", "https://translate.example/v1/chat/completions"),
    (" https://translate.example/v1/ ", "https://translate.example/v1/chat/completions"),
    ("https://translate.example/proxy/v1", "https://translate.example/proxy/v1/chat/completions"),
    ("https://translate.example/v1/chat/completions/", "https://translate.example/v1/chat/completions"),
    ("https://translate.example/v1?token=test", "https://translate.example/v1/chat/completions?token=test"),
])
def test_ai_sends_chat_completion(ai_settings, ai_transport, base, endpoint):
    requests, responses = ai_transport
    ai_settings.translate_ai_api_url = base
    responses.append(completion("  你好\n世界  "))

    assert asyncio.run(translate.translate_text("hello\nworld")) == "你好\n世界"
    request, = requests
    assert request.method == "POST"
    assert str(request.url) == endpoint
    assert request.headers["Authorization"] == "Bearer test-key"
    body = json.loads(request.content)
    assert body["model"] == "test-model"
    assert body["stream"] is False
    assert body["messages"][0]["role"] == "system"
    assert "Simplified Chinese" in body["messages"][0]["content"]
    assert body["messages"][1] == {"role": "user", "content": "hello\nworld"}
    translate._translate_bing.assert_not_awaited()


def test_ai_supports_local_service_and_target_language(ai_settings, ai_transport):
    requests, responses = ai_transport
    ai_settings.translate_ai_api_url = "http://127.0.0.1:1234/v1"
    ai_settings.translate_ai_api_key = ""
    responses.append(completion("翻譯"))
    assert asyncio.run(translate.translate_text("translation", target="zh-TW")) == "翻譯"
    assert "Authorization" not in requests[0].headers
    assert "Traditional Chinese" in json.loads(requests[0].content)["messages"][0]["content"]


@pytest.mark.parametrize("failure", [
    httpx.Response(429, headers={"Retry-After": "1"}),
    httpx.Response(503),
    httpx.ReadTimeout("timed out"),
])
def test_ai_retries_transient_errors(ai_settings, ai_transport, monkeypatch, failure):
    requests, responses = ai_transport
    responses.extend([failure, completion()])
    sleep = AsyncMock()
    monkeypatch.setattr(translate.asyncio, "sleep", sleep)
    assert asyncio.run(translate.translate_text("hello")) == "你好"
    assert len(requests) == 2
    sleep.assert_awaited_once()
    translate._translate_bing.assert_not_awaited()


@pytest.mark.parametrize("response", [
    httpx.Response(401, json={"error": {"message": "invalid key"}}),
    httpx.Response(200, text="invalid JSON"),
    httpx.Response(200, json={"choices": []}),
    completion(""),
    completion("partial", finish_reason="length"),
    completion(None, message={"content": None, "refusal": "refused"}),
])
def test_ai_unusable_response_keeps_original_without_caching(ai_settings, ai_transport, response):
    requests, responses = ai_transport
    responses.extend([response, completion()])
    assert asyncio.run(translate.translate_text("hello")) == "hello"
    assert asyncio.run(translate.translate_text("hello")) == "你好"
    assert len(requests) == 2
    translate._translate_bing.assert_awaited_once_with("hello", "zh-CN")


def test_ai_falls_back_after_exhausting_retries(ai_settings, ai_transport, monkeypatch):
    requests, responses = ai_transport
    responses.extend(httpx.Response(429) for _ in range(3))
    monkeypatch.setattr(translate.asyncio, "sleep", AsyncMock())
    translate._translate_bing.return_value = "备用翻译"
    assert asyncio.run(translate.translate_text("hello")) == "备用翻译"
    assert len(requests) == 3
    translate._translate_bing.assert_awaited_once_with("hello", "zh-CN")


@pytest.mark.parametrize(("url", "model"), [
    ("", "test-model"),
    ("https://translate.example/v1", ""),
    ("ftp://translate.example", "test-model"),
    ("http://[invalid", "test-model"),
    ("http://localhost:invalid", "test-model"),
])
def test_ai_missing_or_invalid_config_falls_back(ai_settings, ai_transport, url, model):
    requests, _ = ai_transport
    ai_settings.translate_ai_api_url = url
    ai_settings.translate_ai_model = model
    assert asyncio.run(translate.translate_text("hello")) == "hello"
    assert requests == []
    translate._translate_bing.assert_awaited_once()


def test_ai_cache_tracks_configuration(ai_settings, ai_transport):
    requests, responses = ai_transport
    responses.append(completion("首次翻译"))
    assert asyncio.run(translate.translate_text("hello")) == "首次翻译"
    assert asyncio.run(translate.translate_text("hello")) == "首次翻译"
    assert len(requests) == 1
    for field, value in [
        ("translate_ai_model", "another-model"),
        ("translate_ai_api_url", "https://another.example/v1"),
        ("translate_ai_api_key", "another-key"),
    ]:
        setattr(ai_settings, field, value)
        responses.append(completion(value))
        assert asyncio.run(translate.translate_text("hello")) == value
    assert len(requests) == 4


def test_ai_keeps_existing_chinese_and_tag_behavior(ai_settings, ai_transport):
    requests, responses = ai_transport
    responses.append(completion("翻译标签"))
    assert asyncio.run(translate.translate_text(None)) is None
    assert asyncio.run(translate.translate_text("  ")) == "  "
    assert asyncio.run(translate.translate_text("已有中文")) == "已有中文"
    assert asyncio.run(translate.translate_tags(["中字", "無碼", "", "tag"])) == [
        "中字", "無碼", "翻译标签",
    ]
    assert len(requests) == 1


def test_ai_settings_persist_without_exposing_key(ai_settings, monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    AppSetting.__table__.create(engine)
    session_factory = sessionmaker(bind=engine)

    def db_session():
        with session_factory() as db:
            yield db

    monkeypatch.setattr(settings_api, "_providers_with_status", AsyncMock(return_value=([], None, False)))
    monkeypatch.setattr(settings_api, "SessionLocal", session_factory)
    app = FastAPI()
    app.include_router(settings_api.router, prefix="/api/settings")
    app.dependency_overrides[get_db] = db_session
    app.dependency_overrides[require_auth] = lambda: {}
    try:
        with TestClient(app) as client:
            response = client.put("/api/settings", json={
                "translate_provider": "ai",
                "translate_ai_api_url": "https://saved.example/v1",
                "translate_ai_api_key": "saved-secret",
                "translate_ai_model": "saved-model",
            })
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["translate_provider"] == "ai"
            assert data["translate_ai_api_key_set"] is True
            assert "saved-secret" not in response.text
            assert "translate_ai_api_key" not in data
            assert "translate_ai_api_key" not in data["extra"]
            assert data["translate_ai_api_url"] == "https://saved.example/v1"
            assert data["translate_ai_model"] == "saved-model"

            # Saving other fields leaves the existing secret intact.
            client.put("/api/settings", json={"translate_ai_model": "updated-model"}).raise_for_status()
            with session_factory() as db:
                assert db.get(AppSetting, "translate_ai_api_key").value == "saved-secret"

            # Startup must restore saved values before a settings GET occurs.
            ai_settings.translate_provider = "google"
            ai_settings.translate_ai_api_url = ""
            ai_settings.translate_ai_api_key = ""
            ai_settings.translate_ai_model = ""
            settings_api.apply_persisted_overrides()
            assert ai_settings.translate_provider == "ai"
            assert ai_settings.translate_ai_api_url == "https://saved.example/v1"
            assert ai_settings.translate_ai_api_key == "saved-secret"
            assert ai_settings.translate_ai_model == "updated-model"
            response = client.get("/api/settings")
            assert response.status_code == 200
            assert "saved-secret" not in response.text

            # An explicit empty key supports switching to an unauthenticated service.
            response = client.put("/api/settings", json={"translate_ai_api_key": ""})
            assert response.status_code == 200
            assert response.json()["translate_ai_api_key_set"] is False
    finally:
        engine.dispose()
