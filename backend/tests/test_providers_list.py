from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import config
from app.api import settings as settings_api
from app.api.settings import parse_priority_list
from app.db import Base, get_db
from app.deps import require_auth
from app.models import AppSetting
from app.services.metatube import parse_movie_provider_names


def test_parse_movie_providers_dict_keys():
    data = {
        "movie_providers": {
            "JavBus": "https://javbus.com",
            "FANZA": "https://dmm.co.jp",
        },
        "actor_providers": {"Gfriends": "https://x"},
    }
    names = parse_movie_provider_names(data)
    assert names == ["FANZA", "JavBus"]


def test_parse_movie_providers_pascal_case():
    data = {"MovieProviders": {"HEYZO": "https://heyzo.com"}}
    assert parse_movie_provider_names(data) == ["HEYZO"]


def test_parse_movie_providers_list_strings():
    data = {"movie_providers": ["FC2", "JavBus", "FC2"]}
    assert parse_movie_provider_names(data) == ["FC2", "JavBus"]


def test_parse_movie_providers_list_dicts():
    data = {
        "movie_providers": [
            {"name": "AVE"},
            {"provider": "SOD"},
            {"id": "MGS"},
            {},
        ]
    }
    assert parse_movie_provider_names(data) == ["AVE", "MGS", "SOD"]


def test_parse_movie_providers_garbage():
    assert parse_movie_provider_names(None) == []
    assert parse_movie_provider_names([]) == []
    assert parse_movie_provider_names({"actor_providers": {"Gfriends": "x"}}) == []
    assert parse_movie_provider_names({"movie_providers": "nope"}) == []


def test_parse_priority_list():
    assert parse_priority_list(None) == []
    assert parse_priority_list("") == []
    assert parse_priority_list('["JavBus","FANZA"]') == ["JavBus", "FANZA"]
    assert parse_priority_list(["A", "A", " B "]) == ["A", "B"]
    assert parse_priority_list("not-json") == []
    assert parse_priority_list("{}") == []
    long = "x" * 100
    assert parse_priority_list([long, "ok"]) == ["ok"]


@pytest.fixture
def provider_api(tmp_path, monkeypatch):
    settings = config.Settings(_env_file=None, scrape_source="stash",
        stash_base_url="http://stash.example", stashscrapers_base_url="http://scrapers.example")
    monkeypatch.setattr(settings_api, "get_settings", lambda: settings)
    calls = []

    async def metatube_catalog(_):
        calls.append("metatube")
        return {"movie_providers": ["MetaSource"]}

    async def stash_catalog(_):
        calls.append("stash")
        return [{"id": "StashSource", "name": "Stash source", "types": ["NAME"]}]

    async def rest_catalog(_):
        calls.append("stashscrapers")
        return [{"id": "Folder/Source", "name": "REST source", "types": ["URL"]}]

    monkeypatch.setattr(settings_api.MetaTubeClient, "list_providers", metatube_catalog)
    monkeypatch.setattr(settings_api.StashClient, "list_scrapers", stash_catalog)
    monkeypatch.setattr(settings_api.StashScrapersClient, "list_scrapers", rest_catalog)
    engine = create_engine(f"sqlite:///{tmp_path.as_posix()}/catalog.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def session():
        with factory() as db:
            yield db

    app = FastAPI()
    app.include_router(settings_api.router, prefix="/api/settings")
    app.dependency_overrides[get_db] = session
    app.dependency_overrides[require_auth] = lambda: {}
    with TestClient(app) as api:
        yield api, settings, calls, factory
    engine.dispose()


@pytest.mark.parametrize("source, expected", [
    ("metatube", "MetaSource"), ("stash", "StashSource"), ("stashscrapers", "Folder/Source"),
    (None, "StashSource"),
])
def test_provider_catalog_can_select_backend_without_changing_global(provider_api, source, expected):
    api, settings, calls, factory = provider_api
    response = api.get("/api/settings/providers", params={"source": source} if source else {})
    assert response.status_code == 200, response.text
    assert response.json()["movie_providers"] == [expected]
    assert calls == [source or "stash"]
    assert settings.scrape_source == "stash"
    with factory() as db:
        assert db.get(AppSetting, "scrape_source") is None
    if source == "stashscrapers":
        assert response.json()["movie_provider_labels"][expected] == "REST source（仅 URL）"


def test_provider_catalog_rejects_unknown_backend(provider_api):
    api, _, calls, _ = provider_api
    assert api.get("/api/settings/providers", params={"source": "unknown"}).status_code == 422
    assert not calls
