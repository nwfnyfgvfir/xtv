import asyncio
import base64
import time
from urllib.parse import quote

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import config
from app.api import media, playback, settings as settings_api
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
