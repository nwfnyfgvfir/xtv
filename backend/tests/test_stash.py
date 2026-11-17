import asyncio
import base64
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import config
from app.api import health, media, playback, settings as settings_api
from app.db import Base, get_db
from app.deps import require_auth
from app.models import AppSetting, Library, MediaItem
from app.services import images, scrape, stash

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jS7sAAAAASUVORK5CYII="
)
INLINE_IMAGE = "data:image/png;base64," + base64.b64encode(PNG).decode()


def graphql(**data):
    return httpx.Response(200, json={"data": data})


def scraper(scraper_id="JavBus", types=None):
    return {
        "id": scraper_id, "name": "Source " + scraper_id,
        "scene": {"supported_scrapes": types or ["NAME", "FRAGMENT", "URL"], "urls": ["https://source.example/"]},
    }


BOX_ENDPOINT = 'https://box.example/graphql'
BOX_SCENE_ID = 'a1406f23-5c83-49a1-9445-1eb7b9b8316f'


def configured_boxes(*boxes, scrapers=None):
    return graphql(listScrapers=scrapers or [], configuration={'general': {'stashBoxes': list(boxes)}})


def box(endpoint=BOX_ENDPOINT, name='StashDB'):
    return {'name': name, 'endpoint': endpoint}


@pytest.fixture
def stash_settings(monkeypatch, tmp_path):
    settings = config.Settings(
        _env_file=None, database_url=f"sqlite:///{tmp_path.as_posix()}/app.db",
        media_root=str(tmp_path / "media"), scrape_source="stash",
        stash_base_url="http://stash.example:9999", stash_api_key="stash-test-secret",
        stash_scraper="JavBus", stash_fallback=False, auto_translate=False,
        metatube_token="", image_proxy_mode="site",
    )
    for module in (config, stash, scrape, settings_api, health):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    return settings


@pytest.fixture
def stash_http(monkeypatch):
    requests, replies = [], []

    def handle(request):
        requests.append(request)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    client_type = httpx.AsyncClient
    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client_type(transport=transport, **kwargs))
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
    app.include_router(playback.router, prefix="/api")
    app.include_router(health.router, prefix="/api")
    app.dependency_overrides[get_db] = session
    app.dependency_overrides[require_auth] = lambda: {}
    with TestClient(app) as client:
        yield client


def seed_media(db, number="ABP-001"):
    library = Library(name="test", path="local", type="local")
    db.add(library)
    db.flush()
    item = MediaItem(
        library_id=library.id, filename=f"{number or 'unknown'}.mp4", path="local/test.mp4",
        number=number, source_type="local", subtitle_flag="C",
    )
    db.add(item)
    db.commit()
    return item


@pytest.mark.parametrize("base", [
    "http://stash.example:9999", "http://stash.example:9999/graphql/",
    "http://stash.example:9999/prefix/graphql",
])
def test_stash_graphql_endpoint_and_auth(stash_settings, stash_http, base):
    requests, replies = stash_http
    stash_settings.stash_base_url = base
    replies.append(graphql(listScrapers=[scraper(), {"id": "actor-only", "scene": None}]))
    rows = asyncio.run(stash.StashClient().list_scrapers())
    assert [s["id"] for s in rows] == ["JavBus"]
    request, = requests
    expected = base.rstrip("/") if base.rstrip("/").endswith("/graphql") else base + "/graphql"
    assert str(request.url) == expected
    assert request.headers["ApiKey"] == "stash-test-secret"
    assert "Authorization" not in request.headers
    assert "listScrapers(types: [SCENE])" in json.loads(request.content)["query"]


def test_stash_name_search_expands_detail_saves_images_and_translates(stash_settings, stash_http, database, api, monkeypatch):
    requests, replies = stash_http
    db, _ = database
    item = seed_media(db)
    stash_settings.auto_translate = True
    monkeypatch.setattr("app.services.translate.translate_text", AsyncMock(side_effect=lambda value: "译：" + value))
    monkeypatch.setattr("app.services.translate.translate_tags", AsyncMock(side_effect=lambda values: values))
    replies.extend([
        graphql(listScrapers=[scraper()]),
        graphql(scrapeSingleScene=[
            {"title": "ABP-001 result", "urls": ["https://source.example/ABP-001"]},
        ]),
        graphql(scrapeSingleScene=[{
            "title": "日本語のタイトル", "code": "ABP-001", "details": "日本語のあらすじ",
            "remote_site_id": "scene-1", "urls": ["https://source.example/ABP-001"],
            "date": "2024-07-10", "duration": 5401, "image": INLINE_IMAGE,
            "studio": {"name": "Studio"}, "tags": [{"name": "Drama"}],
            "performers": [{"name": "Actor Name", "urls": ["https://source.example/actors/1"], "images": [INLINE_IMAGE]}],
        }]),
    ])
    assert asyncio.run(scrape.scrape_media_item(db, item)) is True
    assert item.provider == "stash:JavBus"
    assert item.title == "译：日本語のタイトル"
    assert item.title_original == "日本語のタイトル"
    assert item.plot_original == "日本語のあらすじ"
    assert item.runtime == 91
    assert item.studio == "Studio"
    assert item.release_date == "2024-07-10"
    assert json.loads(item.tags_json) == ["Drama", "中文字幕"]
    assert item.actors[0].name == "Actor Name"
    assert item.cover_url.startswith("/api/images/scraped/")
    assert item.actors[0].image_url == item.cover_url
    assert item.scraped_at is not None
    assert len(requests) == 3
    query = json.loads(requests[1].content)
    assert query["variables"] == {"source": {"scraper_id": "JavBus"}, "input": {"query": "ABP-001"}}
    detail_variables = json.loads(requests[2].content)["variables"]
    assert detail_variables["source"] == {"scraper_id": "JavBus"}
    assert detail_variables["input"]["scene_input"]["urls"] == ["https://source.example/ABP-001"]
    image = api.get(item.cover_url)
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.content == PNG


def test_stash_fragment_and_unauthenticated_service(stash_settings, stash_http):
    requests, replies = stash_http
    stash_settings.stash_api_key = ""
    replies.extend([
        graphql(listScrapers=[scraper("Fragment", ["FRAGMENT"])]),
        graphql(scrapeSingleScene=[{"title": "Full title", "code": "ABP-001"}]),
    ])
    results = asyncio.run(stash.StashClient().search_movie("ABP-001", provider="Fragment", fallback=False))
    assert results[0]["provider"] == "stash:Fragment"
    assert "ApiKey" not in requests[0].headers
    assert json.loads(requests[1].content)["variables"]["input"] == {"scene_input": {"title": "ABP-001", "code": "ABP-001"}}


def test_stash_name_result_uses_url_when_query_fragment_is_unsupported(stash_settings, stash_http):
    requests, replies = stash_http
    replies.extend([
        graphql(listScrapers=[scraper()]),
        graphql(scrapeSingleScene=[{"title": "ABP-001 title", "urls": ["https://source.example/ABP-001"]}]),
        httpx.Response(200, json={"errors": [{"message": "fragment not supported"}]}),
        graphql(scrapeSceneURL={"title": "Full scene", "code": "ABP-001", "details": "Full plot"}),
    ])
    async def run():
        client = stash.StashClient()
        result, = await client.search_movie("ABP-001", provider="JavBus", fallback=False)
        return await client.get_movie(result["provider"], result["id"])

    assert asyncio.run(run())["summary"] == "Full plot"
    assert json.loads(requests[-1].content)["variables"] == {"url": "https://source.example/ABP-001"}


@pytest.mark.parametrize(("types", "scene"), [
    (["NAME"], {"title": "ABP-0010 unrelated"}),
    (["NAME"], {"title": "ABP-001 misleading title", "code": "ABP-002"}),
    (["FRAGMENT"], {"title": "Wrong scene", "code": "ABP-002"}),
])
def test_stash_defers_filename_matching_to_the_source(stash_settings, stash_http, types, scene):
    _, replies = stash_http
    replies.extend([graphql(listScrapers=[scraper(types=types)]), graphql(scrapeSingleScene=[scene])])
    assert asyncio.run(stash.StashClient().search_movie("ABP-001", provider="JavBus", fallback=False))[0]["title"] == scene["title"]


def test_invalid_source_url_does_not_change_media_number(stash_settings, database, api):
    db, _ = database
    item = seed_media(db)
    response = api.post(f"/api/media/{item.id}/rescrape", json={"number": "ABP-002", "url": "file:///invalid"})
    assert response.status_code == 400
    db.refresh(item)
    assert item.number == "ABP-001"


def test_stash_priority_continues_after_graphql_failure(stash_settings, stash_http, database):
    requests, replies = stash_http
    db, _ = database
    item = seed_media(db)
    stash_settings.stash_scraper_priority = '["A", "B"]'
    replies.extend([
        graphql(listScrapers=[scraper("A"), scraper("B")]),
        httpx.Response(200, json={"errors": [{"message": "source down"}], "data": None}),
        graphql(scrapeSingleScene=[{"code": "ABP-001", "title": "Matched"}]),
    ])
    assert asyncio.run(scrape.scrape_media_item(db, item)) is True
    assert item.provider == "stash:B"
    assert [json.loads(r.content)["variables"]["source"]["scraper_id"] for r in requests[1:]] == ["A", "B"]


def test_stash_legacy_disabled_fallback_does_not_disable_remaining_sources(stash_settings, stash_http, database):
    requests, replies = stash_http
    db, _ = database
    replies.extend([graphql(listScrapers=[scraper('A'), scraper('B')]),
        graphql(scrapeSingleScene=[]), graphql(scrapeSingleScene=[{'title': 'Source result', 'code': 'ABP-001'}])])
    stash_settings.stash_scraper, stash_settings.stash_fallback = 'A', False
    stash_settings.stash_scraper_priority = '["A"]'
    item = seed_media(db)
    assert asyncio.run(scrape.scrape_media_item(db, item)) is True
    assert item.provider == 'stash:B' and len(requests) == 3


def test_stash_url_only_scraper_without_number(stash_settings, stash_http, database, api):
    requests, replies = stash_http
    db, _ = database
    item = seed_media(db, number=None)
    replies.append(graphql(scrapeSceneURL={
        "title": "URL scene", "code": "ABP-002", "image": INLINE_IMAGE,
        "urls": ["https://source.example/scene/2"],
    }))
    response = api.post(f"/api/media/{item.id}/rescrape", json={"url": "https://source.example/scene/2"})
    assert response.status_code == 200, response.text
    assert response.json()["number"] == "unknown"
    assert response.json()["provider"] == "stash:url"
    assert response.json()["cover_url"].startswith("/api/images/scraped/")
    assert len(requests) == 1


def test_failed_rescrape_reports_failure_even_for_previously_scraped_item(stash_settings, stash_http, database, api):
    _, replies = stash_http
    db, _ = database
    item = seed_media(db)
    item.scraped_at = datetime.now(timezone.utc)
    item.title = "Existing title"
    db.commit()
    replies.append(graphql(scrapeSceneURL=None))
    response = api.post(f"/api/media/{item.id}/rescrape", json={"url": "https://source.example/missing"})
    assert response.status_code == 502
    db.refresh(item)
    assert item.title == "Existing title"


@pytest.mark.parametrize("response", [
    httpx.Response(401),
    httpx.Response(200, text="not JSON"),
    httpx.Response(200, json={"errors": [{"message": "error with stash-test-secret"}], "data": {"listScrapers": []}}),
    httpx.Response(200, json={"data": None}),
])
def test_stash_rejects_errors_and_redacts_api_key(stash_settings, stash_http, response):
    requests, replies = stash_http
    replies.append(response)
    with pytest.raises(stash.StashError) as error:
        asyncio.run(stash.StashClient().list_scrapers())
    assert "stash-test-secret" not in str(error.value)
    assert len(requests) == 1


def test_stash_retries_transient_transport_errors(stash_settings, stash_http, monkeypatch):
    requests, replies = stash_http
    replies.extend([httpx.Response(503), httpx.ReadTimeout("timeout"), graphql(listScrapers=[])])
    monkeypatch.setattr(stash.asyncio, "sleep", AsyncMock())
    assert asyncio.run(stash.StashClient().list_scrapers()) == []
    assert len(requests) == 3


def test_stash_performer_url_enrichment(stash_settings, stash_http, database):
    _, replies = stash_http
    db, _ = database
    from app.models import Actor

    actor = Actor(name="Actor Name", provider="stash:JavBus", provider_id="https://source.example/actor/1")
    db.add(actor)
    db.commit()
    replies.append(graphql(scrapePerformerURL={"name": "Actor Name", "images": [INLINE_IMAGE]}))
    assert asyncio.run(scrape.enrich_actor_image(db, actor)) is True
    assert actor.image_url.startswith("/api/images/scraped/")


def test_stash_settings_persist_and_keep_secrets_private(stash_settings, stash_http, database, api, monkeypatch):
    _, replies = stash_http
    db, factory = database
    monkeypatch.setattr(settings_api, "SessionLocal", factory)
    monkeypatch.setattr(settings_api, "_providers_with_status", AsyncMock(return_value=(["MetaProvider"], None, False)))
    replies.extend([graphql(listScrapers=[scraper("A"), scraper("URLOnly", ["URL"])]) for _ in range(2)])
    response = api.put("/api/settings", json={
        "scrape_source": "stash", "stash_base_url": "http://saved.example:9999/graphql",
        "stash_api_key": "saved-key", "stash_scraper_priority": ["A", "A"], "stash_fallback": False,
    })
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["stash_api_key_set"] is True
    assert "saved-key" not in response.text
    assert "stash_api_key" not in data
    assert data["stash_scraper_priority"] == ["A"]
    assert data["movie_providers"] == ["A", "URLOnly"]
    assert "仅 URL" in data["movie_provider_labels"]["URLOnly"]
    assert not any(key.startswith("stash_scrapers_cache:") for key in data["extra"])
    api.put("/api/settings", json={"stash_scraper": "A"}).raise_for_status()
    assert db.get(AppSetting, "stash_api_key").value == "saved-key"

    stash_settings.scrape_source = "metatube"
    stash_settings.stash_base_url = ""
    stash_settings.stash_api_key = ""
    stash_settings.stash_scraper_priority = ""
    settings_api.apply_persisted_overrides()
    assert stash_settings.scrape_source == "stash"
    assert stash_settings.stash_base_url == "http://saved.example:9999/graphql"
    assert stash_settings.stash_api_key == "saved-key"
    assert stash_settings.stash_scraper_priority == '["A"]'

    response = api.put("/api/settings", json={"scrape_source": "metatube"})
    assert response.status_code == 200
    assert response.json()["movie_providers"] == ["MetaProvider"]
    assert response.json()["stash_api_key_set"] is True


def test_stash_scraper_cache_is_scoped_to_server(stash_settings, stash_http, database):
    _, replies = stash_http
    db, _ = database
    replies.append(graphql(listScrapers=[scraper("A")]))
    names, _, error, cached = asyncio.run(settings_api._stash_providers_with_status(db))
    assert names == ["A"]
    assert error is None and cached is False
    replies.append(httpx.Response(401))
    names, _, error, cached = asyncio.run(settings_api._stash_providers_with_status(db))
    assert names == ["A"] and cached is True and error
    stash_settings.stash_base_url = "http://another.example:9999"
    replies.append(httpx.Response(401))
    names, _, error, cached = asyncio.run(settings_api._stash_providers_with_status(db))
    assert names == [] and cached is False and error


def test_stash_health_only_checks_selected_source(stash_settings, stash_http, api):
    requests, replies = stash_http
    replies.append(graphql(version={"version": "v-test"}))
    response = api.get("/api/health")
    assert response.status_code == 200
    assert response.json()["stash"]["ok"] is True
    assert response.json()["metatube"] is None
    assert response.json()["scrape_source"] == "stash"
    assert len(requests) == 1


def test_stash_images_bypass_metatube_proxy(stash_settings):
    stash_settings.image_proxy_mode = "metatube"
    url = images.rewrite_image_url("https://images.example/image.jpg", provider="stash:JavBus", provider_id="1")
    assert url == "https://images.example/image.jpg"


def test_media_list_and_actor_media_expose_proxied_backup_artwork(stash_settings, database, api):
    from app.api.actors import _proxy_media
    db, _ = database
    item = seed_media(db)
    item.backdrop_url = 'https://cdn.example/backup.jpg'
    db.commit()
    data = api.get('/api/media').json()['items'][0]
    assert data['backdrop_url'].startswith('/api/images/proxy?')
    assert _proxy_media(item, set()).backdrop_url.startswith('/api/images/proxy?')


@pytest.mark.parametrize("value", [
    "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=", "data:image/png;base64,invalid!", "data:text/html;base64,SGVsbG8=",
])
def test_scraped_images_reject_invalid_or_non_raster_data(stash_settings, value):
    assert images.store_scraped_image(value) is None


def test_stash_auto_fallback_skips_url_only_and_already_attempted_source(stash_settings, stash_http):
    requests, replies = stash_http
    replies.extend([
        graphql(listScrapers=[scraper("A"), scraper("OnlyURL", ["URL"]), scraper("B")]),
        graphql(scrapeSingleScene=[]),
        graphql(scrapeSingleScene=[{"code": "ABP-001", "title": "Full title"}]),
    ])
    client = stash.StashClient()

    async def run():
        assert await client.search_movie("ABP-001", "A", False) == []
        return await client.search_movie("ABP-001")

    rows = asyncio.run(run())
    assert rows[0]["provider"] == "stash:B"
    assert [json.loads(req.content)["variables"]["source"]["scraper_id"] for req in requests[1:]] == ["A", "B"]


def test_stash_configured_boxes_are_listed_without_requesting_their_credentials(stash_settings, stash_http):
    requests, replies = stash_http
    replies.append(configured_boxes(box(), box(), {'name': 'Invalid', 'endpoint': 'file:///private'}, scrapers=[scraper('A')]))
    rows = asyncio.run(stash.StashClient().list_scrapers())
    assert len(rows) == 2 and rows[0]['id'] == 'A'
    assert rows[1]['id'].startswith('stash-box:') and rows[1]['name'] == 'StashDB（Stash-box）'
    assert rows[1]['types'] == ['NAME'] and rows[1]['box_index'] == 0
    query = json.loads(requests[0].content)['query']
    assert 'stashBoxes { name endpoint }' in query and 'api_key' not in query
    assert all(request.url.host == 'stash.example' for request in requests)


def test_box_identity_survives_configuration_reordering(stash_settings, stash_http):
    _, replies = stash_http
    replies.extend([configured_boxes(box(), box('https://other.example/graphql', 'Other')),
        configured_boxes(box('https://other.example/graphql', 'Other'), box())])
    first = asyncio.run(stash.StashClient().list_scrapers())
    second = asyncio.run(stash.StashClient().list_scrapers())
    assert first[0]['id'] == second[1]['id'] and first[0]['box_index'] == 0 and second[1]['box_index'] == 1


def test_stash_box_metadata_uses_stash_endpoint_and_existing_metadata_pipeline(stash_settings, stash_http, database):
    requests, replies = stash_http
    db, _ = database
    stash_settings.stash_scraper = stash._box_id(BOX_ENDPOINT)
    item = seed_media(db)
    replies.extend([configured_boxes(box()), graphql(scrapeSingleScene=[{
        'title': 'Full box title', 'code': 'ABP-001', 'details': 'Full box plot',
        'remote_site_id': BOX_SCENE_ID, 'date': '2025-01-02', 'duration': 1200,
        'urls': [f'https://box.example/scenes/{BOX_SCENE_ID}'], 'image': INLINE_IMAGE,
        'studio': {'name': 'Box studio'}, 'performers': [{'name': 'Box actor', 'remote_site_id': 'actor-id', 'image': INLINE_IMAGE}],
        'tags': [{'name': 'Box tag'}],
    }])])
    assert asyncio.run(scrape.scrape_media_item(db, item)) is True
    assert item.title == 'Full box title' and item.plot == 'Full box plot'
    assert item.runtime == 20 and item.studio == 'Box studio' and item.release_date == '2025-01-02'
    assert item.provider.startswith('stash:stash-box:') and item.provider_id == BOX_SCENE_ID
    assert item.cover_url.startswith('/api/images/scraped/') and item.actors[0].name == 'Box actor'
    assert len(requests) == 2
    assert json.loads(requests[1].content)['variables'] == {'source': {'stash_box_endpoint': BOX_ENDPOINT}, 'input': {'query': 'ABP-001'}}
    assert all(request.url.host == 'stash.example' and request.headers['ApiKey'] == 'stash-test-secret' for request in requests)


@pytest.mark.parametrize('code', ['ABP-002', 'ABP-0010'])
def test_stash_box_matching_is_owned_by_the_source(stash_settings, stash_http, code):
    _, replies = stash_http
    replies.extend([configured_boxes(box()), graphql(scrapeSingleScene=[{'title': 'ABP-001 misleading title', 'code': code}])])
    assert asyncio.run(stash.StashClient().search_movie('ABP-001', stash._box_id(BOX_ENDPOINT), False))[0]['number'] == code


def test_stash_box_participates_in_automatic_fallback(stash_settings, stash_http):
    requests, replies = stash_http
    replies.extend([configured_boxes(box(), scrapers=[scraper('A')]), graphql(scrapeSingleScene=[]),
        graphql(scrapeSingleScene=[{'code': 'ABP-001', 'title': 'Box result'}])])
    rows = asyncio.run(stash.StashClient().search_movie('ABP-001'))
    assert rows[0]['_scraper_id'] == stash._box_id(BOX_ENDPOINT)
    assert json.loads(requests[1].content)['variables']['source'] == {'scraper_id': 'A'}
    assert json.loads(requests[2].content)['variables']['source'] == {'stash_box_endpoint': BOX_ENDPOINT}


def test_legacy_stash_box_index_is_used_only_after_schema_rejection(stash_settings, stash_http):
    requests, replies = stash_http
    replies.extend([configured_boxes(box()), httpx.Response(422, json={'errors': [{'message': 'Field "stash_box_endpoint" is not defined by type "ScraperSourceInput".'}]}),
        graphql(scrapeSingleScene=[{'code': 'ABP-001', 'title': 'Legacy box result'}])])
    rows = asyncio.run(stash.StashClient().search_movie('ABP-001', stash._box_id(BOX_ENDPOINT), False))
    assert rows[0]['title'] == 'Legacy box result'
    assert json.loads(requests[-1].content)['variables']['source'] == {'stash_box_index': 0}


def test_box_auth_failure_does_not_retry_with_another_source_shape(stash_settings, stash_http):
    requests, replies = stash_http
    replies.extend([configured_boxes(box()), httpx.Response(401)])
    with pytest.raises(stash.StashError):
        asyncio.run(stash.StashClient().search_movie('ABP-001', stash._box_id(BOX_ENDPOINT), False))
    assert len(requests) == 2


def test_box_scene_url_uses_scene_uuid_via_stash(stash_settings, stash_http, database, api):
    requests, replies = stash_http
    db, _ = database
    item = seed_media(db, number=None)
    replies.extend([configured_boxes(box()), graphql(scrapeSingleScene=[{
        'title': 'Scene from box URL', 'code': 'ABP-002', 'remote_site_id': BOX_SCENE_ID,
    }])])
    response = api.post(f'/api/media/{item.id}/rescrape', json={'url': f'https://box.example/scenes/{BOX_SCENE_ID}'})
    assert response.status_code == 200 and response.json()['number'] == 'unknown'
    assert response.json()['provider'].startswith('stash:stash-box:')
    assert json.loads(requests[-1].content)['variables'] == {'source': {'stash_box_endpoint': BOX_ENDPOINT}, 'input': {'query': BOX_SCENE_ID}}


def test_explicit_box_source_supports_a_different_public_scene_hostname(stash_settings, stash_http):
    requests, replies = stash_http
    replies.extend([configured_boxes(box('http://internal-box:9998/graphql')), graphql(scrapeSingleScene=[{
        'title': 'Mapped public scene', 'code': 'ABP-001', 'remote_site_id': BOX_SCENE_ID,
    }])])
    result = asyncio.run(stash.StashClient().scrape_url(f'https://public-box.example/scenes/{BOX_SCENE_ID}', provider=stash._box_id('http://internal-box:9998/graphql')))
    assert result[0]['title'] == 'Mapped public scene'
    assert json.loads(requests[-1].content)['variables']['source'] == {'stash_box_endpoint': 'http://internal-box:9998/graphql'}


def test_box_url_never_accepts_a_different_scene_uuid(stash_settings, stash_http):
    _, replies = stash_http
    replies.extend([configured_boxes(box()), graphql(scrapeSingleScene=[{
        'title': 'Wrong scene', 'remote_site_id': 'b75e8417-f991-408d-9015-370f592d358d',
    }])])
    assert asyncio.run(stash.StashClient().scrape_url(f'https://box.example/scenes/{BOX_SCENE_ID}')) == []


def test_box_sources_are_exposed_and_persisted_in_existing_stash_priority_settings(stash_settings, stash_http, database, api):
    _, replies = stash_http
    source_id = stash._box_id(BOX_ENDPOINT)
    replies.append(configured_boxes(box(), scrapers=[scraper('A')]))
    response = api.put('/api/settings', json={'stash_scraper_priority': [source_id, 'A']})
    assert response.status_code == 200
    data = response.json()
    assert data['scrape_source'] == 'stash' and data['stash_scraper_priority'] == [source_id, 'A']
    assert data['movie_provider_labels'][source_id] == 'StashDB（Stash-box）'
    assert BOX_ENDPOINT not in response.text and 'stash-test-secret' not in response.text
