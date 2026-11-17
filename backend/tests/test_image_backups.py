import asyncio
import base64
import time
from unittest.mock import AsyncMock, Mock
from urllib.parse import quote

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import config
from app.api import actors, favorites, media, playback, settings as settings_api
from app.db import Base, get_db
from app.deps import require_auth
from app.models import Actor, AppSetting, ImageBackup, Library, MediaItem, utcnow
from app.services import image_backups as backups, images, stash, stashscrapers

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jS7sAAAAASUVORK5CYII=')
INLINE = 'data:image/png;base64,' + base64.b64encode(PNG).decode()
REMOTE = 'https://cdn.example/cover.png'
TEMPLATE = 'https://proxy.example/image?url={url}'


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    settings = config.Settings(_env_file=None, database_url=f'sqlite:///{tmp_path.as_posix()}/backup.db',
        media_root=str(tmp_path), image_proxy_mode='external', image_external_proxy_url=TEMPLATE,
        image_local_cache=False, auto_translate=False)
    monkeypatch.setattr(config, 'get_settings', lambda: settings)
    monkeypatch.setattr(settings_api, 'get_settings', lambda: settings)
    engine = create_engine(settings.database_url, connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    yield factory, settings
    engine.dispose()


@pytest.fixture
def transport(monkeypatch):
    requests, responses = [], []
    def handle(request):
        requests.append(request)
        return responses.pop(0)
    client_type = httpx.AsyncClient
    mock = httpx.MockTransport(handle)
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: client_type(transport=mock, **kwargs))
    return requests, responses


def seed(factory):
    with factory() as db:
        library = Library(name='Backups', path='fixture')
        db.add(library)
        db.flush()
        item = MediaItem(library_id=library.id, path='fixture.mp4', filename='fixture.mp4',
            cover_url=REMOTE, thumb_url=REMOTE, backdrop_url='https://cdn.example/background.png')
        actor = Actor(name='Fixture performer', image_url='https://cdn.example/actor.png')
        item.actors.append(actor)
        db.add(item)
        db.commit()
        return item.id, actor.id


def test_remote_candidates_are_retained_instead_of_saving_inline_duplicates(workspace):
    factory, settings = workspace
    assert images.first_scraped_image([INLINE, REMOTE]) == REMOTE
    assert stash._image({'images': [INLINE, REMOTE]}) == REMOTE
    normalized = stashscrapers.StashScrapersClient(settings)._normalize({
        'code': 'Fixture', 'images': [INLINE, REMOTE],
        'performers': [{'name': 'Actor', 'images': [INLINE, 'https://cdn.example/actor.png']}],
    }, 'Source', 'Fixture')
    assert normalized['cover_url'] == REMOTE
    assert normalized['actors'][0]['image_url'] == 'https://cdn.example/actor.png'
    assert not (settings.data_dir_path / 'scraped-images').exists()


def test_saved_proxy_urls_follow_the_current_choice_without_nesting(workspace):
    _, settings = workspace
    old = images.site_proxy_url(REMOTE)
    external = TEMPLATE.replace('{url}', quote(REMOTE, safe=''))
    assert images.rewrite_image_url(old) == external
    assert images.rewrite_image_url(external) == external
    assert images.store_scraped_image(old) == REMOTE
    settings.image_proxy_mode = 'site'
    assert images.rewrite_image_url(external) == old
    assert images.rewrite_image_url(old) == old
    settings.image_proxy_mode = 'external'
    assert images.rewrite_image_url('//cdn.example/cover.png') == external
    # A malformed upstream image must not make the entire media response fail.
    assert images.rewrite_image_url('https://[invalid').startswith('https://proxy.example/')


def test_backfill_deduplicates_existing_artwork_and_preserves_original_urls(workspace):
    factory, _ = workspace
    media_id, actor_id = seed(factory)
    worker = backups.ImageBackupWorker(factory)
    worker.backfill()
    worker.backfill()
    with factory() as db:
        assert db.query(ImageBackup).count() == 3
        assert db.get(MediaItem, media_id).cover_url == REMOTE
        assert db.get(Actor, actor_id).image_url == 'https://cdn.example/actor.png'


def test_backup_uses_external_proxy_and_is_exposed_as_a_separate_local_fallback(workspace, transport):
    factory, settings = workspace
    requests, replies = transport
    media_id, _ = seed(factory)
    worker = backups.ImageBackupWorker(factory)
    worker.backfill()
    entry = worker.claim()
    replies.append(httpx.Response(200, content=PNG, headers={'content-type': 'image/png'}))
    asyncio.run(worker.process(entry))
    assert str(requests[0].url) == TEMPLATE.replace('{url}', quote(REMOTE, safe=''))
    with factory() as db:
        item = db.get(MediaItem, media_id)
        output = media._with_proxied_images(item, detail=True)
        assert output.cover_url.startswith('https://proxy.example/')
        assert output.cover_local_url.startswith('/api/images/scraped/')
        assert output.thumb_local_url == output.cover_local_url
        assert images.scraped_image_path(output.cover_local_url.rsplit('/', 1)[-1]).read_bytes() == PNG
        assert item.cover_url == REMOTE
        backups.queue_images(db, [REMOTE])
        db.commit()
        assert db.get(ImageBackup, backups.image_key(REMOTE)).status == 'done'
    # Permanent backups are independent of the optional proxy disk cache.
    assert not settings.image_cache_path.exists()


def test_failed_backup_is_retryable_without_blocking_other_images(workspace, transport):
    factory, _ = workspace
    _, replies = transport
    with factory() as db:
        backups.queue_images(db, [REMOTE, 'https://cdn.example/second.png'])
        db.commit()
    worker = backups.ImageBackupWorker(factory)
    replies.append(httpx.Response(200, content=b'<html>upstream error</html>'))
    failed = worker.claim()
    asyncio.run(worker.process(failed))
    replies.append(httpx.Response(200, content=PNG))
    asyncio.run(worker.process(worker.claim()))
    with factory() as db:
        retry = db.get(ImageBackup, failed[0])
        assert retry.status == 'pending' and retry.attempts == 1 and retry.local_name is None
        assert retry.retry_at.replace(tzinfo=utcnow().tzinfo) > utcnow()
        assert backups.backup_status(db) == {'saved': 1, 'pending': 1, 'running': 0}


def test_worker_restart_recovers_incomplete_downloads(workspace):
    factory, _ = workspace
    with factory() as db:
        backups.queue_images(db, [REMOTE])
        db.commit()
    worker = backups.ImageBackupWorker(factory)
    worker.claim()
    restarted = backups.ImageBackupWorker(factory)
    restarted.backfill()
    assert restarted.claim()[1] == REMOTE


@pytest.mark.parametrize('reply', [
    httpx.Response(302, headers={'location': 'http://127.0.0.1/private.png'}),
    httpx.Response(200, content=b'\x89PNG\r\n\x1a\n' + b'x' * (5 * 1024 * 1024)),
])
def test_private_redirects_and_oversized_bodies_are_not_saved(workspace, transport, reply):
    factory, settings = workspace
    requests, replies = transport
    with factory() as db:
        backups.queue_images(db, [REMOTE])
        db.commit()
    replies.append(reply)
    worker = backups.ImageBackupWorker(factory)
    asyncio.run(worker.process(worker.claim()))
    assert len(requests) == 1
    assert not (settings.data_dir_path / 'scraped-images').exists()
    with factory() as db:
        assert db.query(ImageBackup).one().status == 'pending'


def test_settings_reject_invalid_external_templates_before_persisting(workspace):
    factory, _ = workspace
    app = FastAPI()
    app.include_router(settings_api.router, prefix='/api/settings')
    def session():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = session
    app.dependency_overrides[require_auth] = lambda: {}
    with TestClient(app) as api:
        for template in ('', 'https://proxy.example/no-placeholder', 'file:///tmp/{url}', 'https://{url}/image'):
            response = api.put('/api/settings', json={'image_proxy_mode': 'external', 'image_external_proxy_url': template})
            assert response.status_code == 422
    with factory() as db:
        assert db.query(AppSetting).count() == 0


def test_worker_downloads_at_most_two_images_concurrently(workspace, monkeypatch):
    factory, _ = workspace
    active, peak = 0, 0
    class Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(.04)
            active -= 1
            return httpx.Response(200, content=PNG)
    client_type = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: client_type(transport=Transport(), **kwargs))
    with factory() as db:
        backups.queue_images(db, [f'https://cdn.example/{index}.png' for index in range(6)])
        db.commit()
    worker = backups.ImageBackupWorker(factory, can_run=lambda: True)
    worker.start()
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with factory() as db:
                if backups.backup_status(db)['saved'] == 6:
                    break
            time.sleep(.02)
        else:
            pytest.fail('Backups did not complete')
        assert peak == 2
    finally:
        worker.stop()


@pytest.mark.parametrize('base', ['', 'https://images.example', 'https://images.example/tv', 'http://localhost:8001'])
def test_site_image_host_applies_to_inline_images_and_proxy_without_nesting(workspace, base):
    _, settings = workspace
    settings.image_site_base_url = base
    local = images.store_scraped_image(INLINE)
    assert local.startswith('/api/images/scraped/')
    for mode in ('site', 'external', 'metatube'):
        settings.image_proxy_mode = mode
        assert images.rewrite_image_url(local) == base + local
        assert images.rewrite_image_url(base + local) == base + local
        assert images.store_scraped_image(base + local) == local
    proxy = base + '/api/images/proxy?url=' + quote(REMOTE, safe='')
    assert images.site_proxy_url(REMOTE) == proxy
    assert images.site_proxy_url(proxy) == proxy
    assert images.original_image_url(proxy) == REMOTE
    settings.image_proxy_mode = 'site'
    assert images.rewrite_image_url(proxy) == proxy
    settings.image_proxy_mode = 'external'
    assert images.rewrite_image_url(proxy) == TEMPLATE.replace('{url}', quote(REMOTE, safe=''))
    assert images.site_image_url('/api/images/backups') == '/api/images/backups'
    assert images.site_image_url('/api/stream/1') == '/api/stream/1'


def test_site_image_host_is_scoped_to_its_origin_and_complete_prefix(workspace):
    _, settings = workspace
    settings.image_site_base_url = 'https://images.example/tv'
    assert images.site_image_path('https://IMAGES.example:443/tv/api/images/proxy?url=x') == '/api/images/proxy?url=x'
    for url in (
        'https://images.example.evil/tv/api/images/scraped/a.png',
        'https://images.example:444/tv/api/images/scraped/a.png',
        'http://images.example/tv/api/images/scraped/a.png',
        'https://images.example/tv2/api/images/scraped/a.png',
        'https://images.example/api/images/scraped/a.png',
        'https://images.example/tv/api/images/backups',
    ):
        assert images.site_image_path(url) is None
        assert images.site_image_url(url) == url


def test_backups_change_hosts_without_migrating_metadata_or_files(workspace):
    factory, settings = workspace
    media_id, actor_id = seed(factory)
    local = images.store_image_bytes(PNG)
    worker = backups.ImageBackupWorker(factory)
    worker.backfill()
    with factory() as db:
        for row in db.query(ImageBackup):
            row.status, row.local_name = 'done', local.rsplit('/', 1)[-1]
        db.commit()
        before = [(row.url_hash, row.url, row.status, row.local_name, row.updated_at) for row in db.query(ImageBackup)]
        file = images.scraped_image_path(local.rsplit('/', 1)[-1])
        modified = file.stat().st_mtime_ns
        item, actor = db.get(MediaItem, media_id), db.get(Actor, actor_id)
        for base in ('https://b.example', 'https://new.example/tv', ''):
            settings.image_site_base_url = base
            for data in (media._with_proxied_images(item, detail=True), favorites._to_item(item), actors._proxy_media(item, set())):
                assert data.cover_url.startswith('https://proxy.example/')
                assert data.cover_local_url == data.thumb_local_url == data.backdrop_local_url == base + local
            for data in (actors._actor_item(actor), favorites._to_actor_item(actor, 1)):
                assert data.image_url.startswith('https://proxy.example/')
                assert data.image_local_url == base + local
            assert item.cover_url == REMOTE
            assert not db.dirty
        assert [(row.url_hash, row.url, row.status, row.local_name, row.updated_at) for row in db.query(ImageBackup)] == before
        assert file.read_bytes() == PNG and file.stat().st_mtime_ns == modified
    # Local inline artwork, including an already published B URL, never enters the remote backup queue.
    settings.image_site_base_url = 'https://b.example/tv'
    with factory() as db:
        backups.queue_images(db, [local, settings.image_site_base_url + local])
        db.commit()
        assert db.query(ImageBackup).count() == 3


def test_site_mode_backup_fetches_original_without_calling_the_browser_image_host(workspace, transport):
    factory, settings = workspace
    settings.image_proxy_mode = 'site'
    settings.image_site_base_url = 'http://127.0.0.1:12345/tv'
    requests, replies = transport
    replies.append(httpx.Response(200, content=PNG))
    with factory() as db:
        backups.queue_images(db, [images.site_proxy_url(REMOTE)])
        db.commit()
    worker = backups.ImageBackupWorker(factory)
    asyncio.run(worker.process(worker.claim()))
    assert [str(request.url) for request in requests] == [REMOTE]
    with factory() as db:
        row = db.query(ImageBackup).one()
        assert row.status == 'done' and row.url == REMOTE


def test_metatube_remote_route_is_unchanged_by_the_site_image_host(workspace):
    _, settings = workspace
    settings.image_proxy_mode = 'metatube'
    settings.metatube_base_url = 'https://metatube.example'
    settings.metatube_token = ''
    before = images.rewrite_image_url(REMOTE, provider='JavBus', provider_id='Fixture')
    settings.image_site_base_url = 'https://b.example/tv'
    assert images.rewrite_image_url(REMOTE, provider='JavBus', provider_id='Fixture') == before
    assert images.rewrite_image_url(REMOTE, provider='stash:Fixture', provider_id='Fixture') == REMOTE


@pytest.fixture
def settings_client(workspace, monkeypatch):
    factory, _ = workspace
    monkeypatch.setattr(settings_api, '_providers_with_status', AsyncMock(return_value=([], None, False)))
    app = FastAPI()
    app.include_router(settings_api.router, prefix='/api/settings')
    def session():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = session
    app.dependency_overrides[require_auth] = lambda: {}
    with TestClient(app) as api:
        yield api


def test_site_image_setting_is_persisted_restored_and_clearable(settings_client, workspace, monkeypatch):
    factory, settings = workspace
    with factory() as db:
        backups.queue_images(db, [REMOTE])
        db.commit()
        before = db.query(ImageBackup).one().retry_at
    notify = Mock()
    monkeypatch.setattr(backups.worker, 'notify', notify)
    api = settings_client
    assert api.get('/api/settings').json()['image_site_base_url'] == ''
    response = api.put('/api/settings', json={'image_site_base_url': ' https://b.example/tv/// '})
    assert response.status_code == 200
    assert response.json()['image_site_base_url'] == 'https://b.example/tv'
    # Applying the saved overrides to a fresh runtime uses the DB value over env defaults.
    restored = config.Settings(_env_file=None, image_site_base_url='https://env.example')
    monkeypatch.setattr(settings_api, 'get_settings', lambda: restored)
    with factory() as db:
        assert db.get(AppSetting, 'image_site_base_url').value == 'https://b.example/tv'
        settings_api._apply_overrides_to_runtime(settings_api._db_map(db))
        assert restored.image_site_base_url == 'https://b.example/tv'
        assert db.query(ImageBackup).one().retry_at == before
    assert api.put('/api/settings', json={'image_site_base_url': None}).json()['image_site_base_url'] == 'https://b.example/tv'
    assert api.put('/api/settings', json={'image_site_base_url': ''}).json()['image_site_base_url'] == ''
    assert api.get('/api/settings').json()['image_site_base_url'] == ''
    assert restored.image_site_base_url == ''
    notify.assert_not_called()


@pytest.mark.parametrize('value', [
    '/', 'images.example', '//b.example', 'file:///tmp', 'javascript:alert(1)',
    'https://user:password@b.example', 'https://b.example?token=x', 'https://b.example#fragment',
    'https://b.example:invalid', 'https://b.example/a/../tv', 'https://b.example/%2e%2e/tv',
    'https://b.example/api/images/proxy', 'https://b.example/a\\b', 'https://b.example/a b',
])
def test_invalid_site_image_hosts_do_not_change_saved_settings(settings_client, workspace, value):
    factory, settings = workspace
    response = settings_client.put('/api/settings', json={'image_site_base_url': value, 'auto_scrape': False})
    assert response.status_code == 422
    assert '本站图片访问地址' in response.json()['detail']
    assert settings.image_site_base_url == ''
    with factory() as db:
        assert db.query(AppSetting).count() == 0
    with pytest.raises(ValueError):
        config.Settings(_env_file=None, image_site_base_url=value)
