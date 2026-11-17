import asyncio
import base64
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import config
from app.api import health, media, settings as settings_api
from app.db import Base, get_db
from app.deps import require_auth
from app.models import AppSetting, Library, MediaItem
from app.services import images, scrape, stashscrapers as rest

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jS7sAAAAASUVORK5CYII=")
INLINE = "data:image/png;base64," + base64.b64encode(PNG).decode()


def operation(name, kind="scene", state="available"):
    return {"object": kind, "operation": name, "state": state, "urls": ["https://source.example/"]}


def entry(scraper_id="Folder/Source", names=("name", "query_fragment", "url"), version="v1", enabled=True):
    return {"id": scraper_id, "name": "Source " + scraper_id, "version": version, "enabled": enabled,
            "state": "available", "operations": [operation(name) for name in names]}


def catalog(*entries):
    return httpx.Response(200, json={"scrapers": entries or [entry()]})


def result(code="ABP-001", **values):
    row = {"code": code, "title": "Title " + code, "urls": ["https://source.example/" + code],
           "raw": {"code": code, "urls": ["https://source.example/" + code]}, "images": [], "performers": [], "tags": []}
    row.update(values)
    return row


def response(*rows, version="v1"):
    return httpx.Response(200, json={"results": list(rows), "rules_version": version, "warnings": []})


def error(status, code, message="test failure"):
    return httpx.Response(status, json={"error": {"code": code, "message": message}})


@pytest.fixture
def rest_settings(monkeypatch, tmp_path):
    settings = config.Settings(_env_file=None, database_url=f"sqlite:///{tmp_path.as_posix()}/app.db",
        media_root=str(tmp_path / "media"), scrape_source="stashscrapers",
        stashscrapers_base_url="http://scrapers.example:8080/api", stashscrapers_token="rest-test-secret",
        stashscrapers_scraper="Folder/Source", stashscrapers_fallback=False,
        auto_translate=False, metatube_token="", image_proxy_mode="site")
    for module in (config, rest, scrape, settings_api, health):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    return settings


@pytest.fixture
def rest_http(monkeypatch):
    requests, replies = [], []
    def handle(request):
        requests.append(request)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
    client = httpx.AsyncClient
    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client(transport=transport, **kwargs))
    return requests, replies


@pytest.fixture
def database():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        yield db, factory
    engine.dispose()


@pytest.fixture
def api(database):
    _, factory = database
    def session():
        with factory() as db:
            yield db
    app = FastAPI()
    app.include_router(settings_api.router, prefix="/api/settings")
    app.include_router(media.router, prefix="/api/media")
    app.include_router(health.router, prefix="/api")
    app.dependency_overrides[get_db] = session
    app.dependency_overrides[require_auth] = lambda: {}
    with TestClient(app) as client:
        yield client


def seed(db, number="ABP-001"):
    library = Library(name="REST test", path="local", type="local")
    db.add(library)
    db.flush()
    item = MediaItem(library_id=library.id, path="local/test.mp4", filename=f"{number or 'unknown'}.mp4", number=number, title="Old title", source_type="local")
    db.add(item)
    db.commit()
    return item


@pytest.mark.parametrize(("raw", "expected"), [
    ("http://host:8080", "http://host:8080"),
    ("http://host:8080/api/", "http://host:8080"),
    ("https://host/prefix/api", "https://host/prefix"),
    ("ftp://host", ""), ("http://host:invalid", ""),
    ("http://user:password@host", ""), ("https://host?token=secret", ""),
])
def test_service_address(raw, expected):
    assert rest.service_url(raw) == expected


def test_catalog_filters_capabilities_and_preserves_directory_ids(rest_settings, rest_http):
    requests, replies = rest_http
    partial = entry("Partial")
    partial["operations"] = [operation("name"), operation("url", state="missing_dependency")]
    performer = entry("Performer")
    performer["operations"] = [operation("name", kind="performer")]
    replies.append(catalog(entry(), entry("OnlyURL", ("url",)), entry("Off", enabled=False), partial, performer))
    client = rest.StashScrapersClient()
    rows = asyncio.run(client.list_scrapers())
    assert [row["id"] for row in rows] == ["Folder/Source", "OnlyURL", "Partial"]
    assert rows[1]["types"] == ["URL"]
    assert rows[2]["types"] == ["NAME"]
    assert asyncio.run(client.list_scrapers()) == rows
    assert len(requests) == 1
    assert requests[0].url.path == "/api/scrapers"
    assert requests[0].headers["authorization"] == "Bearer rest-test-secret"


def test_name_search_expands_exact_candidate_with_original_fragment_and_version(rest_settings, rest_http, database, monkeypatch):
    requests, replies = rest_http
    raw = {"title": "Search title", "urls": ["https://source.example/ABP-001"], "custom": {"selection": 7}}
    replies.extend([catalog(), response(result(raw=raw), result("ABP-0012")), response(result(
        title="日本語タイトル", details="日本語あらすじ", date="2024-07-10", duration=5401,
        images=[INLINE], studio={"name": "Studio"}, tags=[{"name": "Drama"}],
        performers=[{"name": "Actor", "urls": ["https://source.example/actor/1"], "images": [INLINE]}],
    ))])
    translated = AsyncMock()
    monkeypatch.setattr(scrape, "apply_translations", translated)
    rest_settings.auto_translate = True
    db, _ = database
    item = seed(db)
    assert asyncio.run(scrape.scrape_media_item(db, item, force=True)) is True
    assert item.title == "日本語タイトル" and item.plot == "日本語あらすじ"
    assert item.runtime == 91 and item.studio == "Studio"
    assert item.provider == "stashscrapers:Folder/Source"
    assert item.cover_url.startswith("/api/images/scraped/")
    assert len(item.actors) == 1 and item.actors[0].image_url.startswith("/api/images/scraped/")
    assert translated.await_count == 1
    assert json.loads(requests[1].content)["query"] == "ABP-001"
    detail = json.loads(requests[2].content)
    assert detail["operation"] == "query_fragment"
    assert detail["fragment"] == raw and detail["rules_version"] == "v1"
    assert len(requests) == 3


def test_search_uses_provider_ranking_without_inferring_catalog_codes(rest_settings, rest_http):
    _, replies = rest_http
    replies.extend([catalog(), response(result('provider-code')), response(result('provider-code', title='Matched by source'))])
    rows = asyncio.run(rest.StashScrapersClient().search_movie('original filename', 'Folder/Source', False))
    assert rows[0]['title'] == 'Matched by source' and rows[0]['number'] == 'provider-code'


def test_fragment_only_scraper_receives_catalog_filename(rest_settings, rest_http):
    requests, replies = rest_http
    replies.extend([catalog(entry(names=("fragment",))), response(result())])
    rows = asyncio.run(rest.StashScrapersClient().search_movie("ABP-001", "Folder/Source", False))
    assert rows[0]["number"] == "ABP-001"
    body = json.loads(requests[1].content)
    assert body["operation"] == "fragment"
    assert body["fragment"]["filename"] == "ABP-001.mp4" and body["rules_version"] == "v1"


def test_url_only_scraper_does_not_search_and_can_fill_missing_number(rest_settings, rest_http, database, api):
    requests, replies = rest_http
    db, _ = database
    item = seed(db, None)
    replies.extend([catalog(entry("Folder/Source", ("url",))), response(result())])
    out = api.post(f"/api/media/{item.id}/rescrape", json={"url": "https://source.example/ABP-001", "provider": "Folder/Source", "fallback": False})
    assert out.status_code == 200, out.text
    assert out.json()["number"] == "unknown"
    assert [request.url.path for request in requests] == ["/api/scrapers", "/api/detail"]
    assert json.loads(requests[1].content)["scraper_id"] == "Folder/Source"


def test_url_scraping_respects_provider_and_fallback(rest_settings, rest_http):
    requests, replies = rest_http
    replies.extend([catalog(entry("A", ("url",)), entry("B", ("url",))), error(404, "not_found"), response(result())])
    rows = asyncio.run(rest.StashScrapersClient().scrape_url("https://source.example/ABP-001", "A", True))
    assert rows[0]["provider"] == "stashscrapers:B"
    assert [json.loads(req.content)["scraper_id"] for req in requests[1:]] == ["A", "B"]


def test_version_conflict_repeats_search_once_and_uses_new_snapshot(rest_settings, rest_http):
    requests, replies = rest_http
    replies.extend([catalog(), response(result()), error(409, "version_conflict"),
                    catalog(entry(version="v2")), response(result(), version="v2"), response(result(title="New version"), version="v2")])
    rows = asyncio.run(rest.StashScrapersClient().search_movie("ABP-001", "Folder/Source", False))
    assert rows[0]["title"] == "New version"
    assert len(requests) == 6
    assert json.loads(requests[5].content)["rules_version"] == "v2"


def test_repeated_version_conflict_never_saves_partial_search_result(rest_settings, rest_http, database, api):
    _, replies = rest_http
    db, _ = database
    item = seed(db)
    for _ in range(2):
        replies.extend([catalog(), response(result()), error(409, "version_conflict")])
    out = api.post(f"/api/media/{item.id}/rescrape", json={"provider": "Folder/Source", "fallback": False})
    assert out.status_code == 502
    db.refresh(item)
    assert item.title == "Old title" and item.scraped_at is None


@pytest.mark.parametrize("reply", [
    httpx.Response(200, text="<html>wrong endpoint</html>"),
    httpx.Response(200, json=[]), httpx.Response(200, json={"scrapers": "wrong"}),
    error(401, "unauthorized", "token rest-test-secret invalid"),
    httpx.ConnectError("connection failed"),
])
def test_invalid_or_failed_responses_are_redacted(rest_settings, rest_http, reply):
    _, replies = rest_http
    replies.append(reply)
    with pytest.raises(rest.StashScrapersError) as caught:
        asyncio.run(rest.StashScrapersClient().list_scrapers())
    assert "rest-test-secret" not in str(caught.value)


def test_settings_separate_backends_preserve_tokens_and_cache_by_server(rest_settings, rest_http, database, api, monkeypatch):
    _, replies = rest_http
    db, factory = database
    monkeypatch.setattr(settings_api, "SessionLocal", factory)
    monkeypatch.setattr(settings_api, "_providers_with_status", AsyncMock(return_value=(["Meta"], None, False)))
    monkeypatch.setattr(settings_api, "_stash_providers_with_status", AsyncMock(return_value=(["Stash"], {"Stash": "Stash"}, None, False)))
    replies.extend([catalog(entry("A"), entry("OnlyURL", ("url",))) for _ in range(2)])
    out = api.put("/api/settings", json={"scrape_source": "stashscrapers", "stashscrapers_base_url": "http://saved.example:8080",
        "stashscrapers_token": "saved-rest-token", "stashscrapers_scraper_priority": ["A", "A"], "stashscrapers_fallback": False,
        "stash_scraper_priority": ["OldStash"], "metatube_provider_priority": ["OldMeta"]})
    assert out.status_code == 200, out.text
    data = out.json()
    assert data["stashscrapers_token_set"] and "saved-rest-token" not in out.text
    assert data["stashscrapers_scraper_priority"] == ["A"]
    assert data["stash_scraper_priority"] == ["OldStash"] and data["metatube_provider_priority"] == ["OldMeta"]
    assert "仅 URL" in data["movie_provider_labels"]["OnlyURL"]
    assert not any(key.startswith("stashscrapers_catalog_cache:") for key in data["extra"])
    api.put("/api/settings", json={"stashscrapers_scraper": "A"}).raise_for_status()
    assert db.get(AppSetting, "stashscrapers_token").value == "saved-rest-token"
    rest_settings.stashscrapers_base_url = ""
    rest_settings.stashscrapers_token = ""
    settings_api.apply_persisted_overrides()
    assert rest_settings.stashscrapers_base_url == "http://saved.example:8080"
    assert rest_settings.stashscrapers_token == "saved-rest-token"
    assert api.put("/api/settings", json={"scrape_source": "stash"}).json()["movie_providers"] == ["Stash"]
    assert api.put("/api/settings", json={"scrape_source": "metatube"}).json()["movie_providers"] == ["Meta"]


def test_catalog_cache_is_scoped_to_endpoint_and_token(rest_settings, rest_http, database):
    _, replies = rest_http
    db, _ = database
    replies.extend([catalog(entry("A")), error(401, "unauthorized"), error(401, "unauthorized")])
    get = settings_api._stashscrapers_providers_with_status
    assert asyncio.run(get(db))[0] == ["A"]
    assert asyncio.run(get(db))[3] is True
    rest_settings.stashscrapers_token = "new-token"
    names, _, failure, cached = asyncio.run(get(db))
    assert names == [] and failure and not cached


def test_health_checks_readiness_and_authenticated_catalog(rest_settings, rest_http, api):
    requests, replies = rest_http
    replies.extend([httpx.Response(200, json={"status": "ok", "ready": True, "rules_version": "v1"}), catalog()])
    data = api.get("/api/health").json()
    assert data["stashscrapers"]["ok"] is True
    assert data["stash"] is None and data["metatube"] is None
    assert data["scrape_source"] == "stashscrapers" and len(requests) == 2
    replies.extend([httpx.Response(200, json={"status": "ok", "ready": True}), error(401, "unauthorized")])
    assert api.get("/api/health").json()["stashscrapers"]["ok"] is False
    replies.append(httpx.Response(200, json={"status": "ok", "ready": False}))
    assert api.get("/api/health").json()["stashscrapers"]["ok"] is False


def test_standalone_provider_images_bypass_metatube(rest_settings):
    rest_settings.image_proxy_mode = "metatube"
    assert images.rewrite_image_url("https://images.example/photo.jpg", provider="stashscrapers:Source", provider_id="id").startswith("/api/images/proxy?")


def test_priority_chain_continues_after_failed_scraper(rest_settings, rest_http, database):
    requests, replies = rest_http
    rest_settings.stashscrapers_scraper_priority = '["Broken","Working"]'
    replies.extend([catalog(entry("Broken", ("fragment",)), entry("Working", ("fragment",))),
                    error(502, "network_error"), response(result())])
    db, _ = database
    item = seed(db)
    assert asyncio.run(scrape.scrape_media_item(db, item, force=True)) is True
    assert item.provider == "stashscrapers:Working"
    assert [json.loads(req.content)["scraper_id"] for req in requests[1:]] == ["Broken", "Working"]


def test_performer_portrait_uses_same_standalone_source(rest_settings, rest_http):
    _, replies = rest_http
    source = entry()
    source["operations"].append(operation("url", kind="performer"))
    replies.extend([catalog(source), response(result(name="Actor", images=[INLINE]))])
    actor = asyncio.run(rest.StashScrapersClient().get_actor("stashscrapers:Folder/Source", "https://source.example/actor/1"))
    assert actor["name"] == "Actor" and actor["image_url"].startswith("/api/images/scraped/")


def test_scrape_response_requires_rules_version(rest_settings, rest_http):
    _, replies = rest_http
    replies.extend([catalog(), httpx.Response(200, json={"results": [result()]})])
    with pytest.raises(rest.StashScrapersError, match="rules version"):
        asyncio.run(rest.StashScrapersClient().search_movie("ABP-001", "Folder/Source", False))


def test_url_pattern_in_query_does_not_match_another_host(rest_settings, rest_http):
    requests, replies = rest_http
    replies.append(catalog(entry(names=("url",))))
    assert asyncio.run(rest.StashScrapersClient().scrape_url("https://unrelated.example/?next=https://source.example/ABP-001")) == []
    assert len(requests) == 1


def test_fragment_metadata_without_returned_code_is_not_discarded(rest_settings, rest_http):
    _, replies = rest_http
    replies.extend([catalog(entry(names=("fragment",))), response(result(code="", title="A real title", urls=[]))])
    rows = asyncio.run(rest.StashScrapersClient().search_movie("ABP-001", "Folder/Source", False))
    assert len(rows) == 1 and rows[0]["title"] == "A real title"
    assert rows[0]["number"] == ""


def test_name_error_still_tries_fragment_in_the_same_scraper(rest_settings, rest_http):
    requests, replies = rest_http
    replies.extend([catalog(entry(names=("name", "fragment"))), error(502, "parse_error"), response(result())])
    rows = asyncio.run(rest.StashScrapersClient().search_movie("ABP-001", "Folder/Source", False))
    assert rows[0]["number"] == "ABP-001"
    assert [request.url.path for request in requests] == ["/api/scrapers", "/api/search", "/api/detail"]


def test_query_fragment_error_still_tries_url_details(rest_settings, rest_http):
    requests, replies = rest_http
    replies.extend([catalog(), response(result()), error(422, "unsupported"), response(result(title="Full URL detail"))])
    rows = asyncio.run(rest.StashScrapersClient().search_movie("ABP-001", "Folder/Source", False))
    assert rows[0]["title"] == "Full URL detail"
    assert json.loads(requests[-1].content)["url"] == "https://source.example/ABP-001"


def test_fragment_receives_real_filename_from_media_item(rest_settings, rest_http, database):
    requests, replies = rest_http
    db, _ = database
    item = seed(db, "010124-001")
    item.filename = "1pondo-010124_001-C.mp4"
    replies.extend([catalog(entry(names=("fragment",))), response(result(code="", title="Date catalog title", urls=[]))])
    assert asyncio.run(scrape.scrape_media_item(db, item, force=True)) is True
    assert json.loads(requests[1].content)["fragment"]["filename"] == item.filename


def test_auto_fallback_does_not_retry_already_attempted_priority_source(rest_settings, rest_http):
    requests, replies = rest_http
    replies.extend([catalog(entry("A", ("fragment",)), entry("B", ("fragment",))),
                    error(404, "not_found"), response(result())])
    client = rest.StashScrapersClient()
    async def run():
        assert await client.search_movie("ABP-001", "A", False) == []
        rows = await client.search_movie("ABP-001", "", True)
        return rows
    rows = asyncio.run(run())
    assert rows[0]["provider"] == "stashscrapers:B"
    assert [json.loads(req.content)["scraper_id"] for req in requests[1:]] == ["A", "B"]


def test_code_only_result_does_not_prevent_a_later_source_from_running(rest_settings, rest_http):
    requests, replies = rest_http
    replies.extend([catalog(entry("A", ("fragment",)), entry("B", ("fragment",))),
                    response({"code": "ABP-001", "raw": {}, "urls": [], "images": []}),
                    response(result(title="Useful metadata"))])
    rows = asyncio.run(rest.StashScrapersClient().search_movie("ABP-001"))
    assert rows[0]["provider"] == "stashscrapers:B"


def test_fragment_keeps_the_original_filename_without_number_inference(rest_settings, rest_http):
    requests, replies = rest_http
    replies.extend([catalog(entry(names=("fragment",))), response(result())])
    asyncio.run(rest.StashScrapersClient().search_movie("ABP-001", "Folder/Source", False, filename="ABP-002.mp4"))
    assert json.loads(requests[1].content)["fragment"]["filename"] == "ABP-002.mp4"


def test_no_priority_or_single_source_tries_eligible_sources_in_catalog_order(rest_settings, rest_http, database):
    requests, replies = rest_http
    rest_settings.stashscrapers_scraper = ""
    rest_settings.stashscrapers_fallback = False
    missing = entry("Missing", ("fragment",))
    missing["operations"][0]["state"] = "missing_dependency"
    replies.extend([catalog(entry("OnlyURL", ("url",)), entry("Off", enabled=False), missing,
                            entry("First", ("fragment",)), entry("Second", ("fragment",)), entry("Later", ("fragment",))),
                    response(), response(result())])
    db, _ = database
    item = seed(db)
    assert asyncio.run(scrape.scrape_media_item(db, item, force=True)) is True
    assert item.provider == "stashscrapers:Second"
    assert [json.loads(req.content)["scraper_id"] for req in requests[1:]] == ["First", "Second"]


@pytest.mark.parametrize("fallback", [False, True])
def test_legacy_single_source_and_fallback_no_longer_restrict_sources(rest_settings, rest_http, database, fallback):
    requests, replies = rest_http
    rest_settings.stashscrapers_scraper = "First"
    rest_settings.stashscrapers_fallback = fallback
    replies.extend([catalog(entry("First", ("fragment",)), entry("Second", ("fragment",))), response()])
    replies.append(response(result()))
    db, _ = database
    item = seed(db)
    assert asyncio.run(scrape.scrape_media_item(db, item, force=True)) is True
    expected = ["First", "Second"]
    assert [json.loads(req.content)["scraper_id"] for req in requests[1:]] == expected
    assert bool(item.scraped_at) is True


@pytest.mark.parametrize("url", [None, "https://source.example/ABP-001"])
def test_service_auth_failure_stops_the_entire_priority_chain(rest_settings, rest_http, database, url):
    requests, replies = rest_http
    rest_settings.stashscrapers_scraper_priority = '["First","Second"]'
    rest_settings.stashscrapers_fallback = True
    replies.extend([catalog(entry("First", ("fragment", "url")), entry("Second", ("fragment", "url"))),
                    error(401, "unauthorized")])
    db, _ = database
    item = seed(db)
    assert asyncio.run(scrape.scrape_media_item(db, item, force=True, url_override=url)) is False
    assert len(requests) == 2 and item.scraped_at is None


def test_fc2_ppv_alias_matches_normalized_media_number(rest_settings, rest_http, database):
    _, replies = rest_http
    replies.extend([catalog(entry(names=("fragment",))), response(result(code="FC2-PPV-123456"))])
    db, _ = database
    item = seed(db, "FC2-123456")
    assert asyncio.run(scrape.scrape_media_item(db, item, force=True)) is True
    assert item.number == "FC2-123456" and item.provider == "stashscrapers:Folder/Source"


def test_source_filename_and_fc2_ppv_are_sent_verbatim_and_never_replaced_by_source_code(rest_settings, rest_http, database):
    requests, replies = rest_http
    db, _ = database
    item = seed(db, 'FC2-1066192')
    item.filename = 'fc2_PPV_1066192 - 中文 1080p.mp4'
    replies.extend([catalog(entry(names=('fragment',))), response(result(code='FC2-1066192'))])
    assert asyncio.run(scrape.scrape_media_item(db, item, force=True)) is True
    fragment = json.loads(requests[1].content)['fragment']
    assert fragment['filename'] == item.filename
    assert fragment['title'] == fragment['code'] == 'fc2_PPV_1066192 - 中文 1080p'
    assert item.number == 'fc2_PPV_1066192 - 中文 1080p'


def test_concurrency_setting_is_validated_and_persisted(rest_settings, database, api, monkeypatch):
    db, factory = database
    monkeypatch.setattr(settings_api, 'SessionLocal', factory)
    monkeypatch.setattr(settings_api, '_stashscrapers_providers_with_status', AsyncMock(return_value=([], {}, None, False)))
    response = api.put('/api/settings', json={'task_concurrency': 4})
    assert response.status_code == 200 and response.json()['task_concurrency'] == 4
    assert db.get(AppSetting, 'task_concurrency').value == '4'
    assert rest_settings.task_concurrency == 4
    assert api.put('/api/settings', json={'task_concurrency': 0}).status_code == 422
    assert api.put('/api/settings', json={'task_concurrency': 9}).status_code == 422
