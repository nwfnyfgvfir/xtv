import base64
from collections import OrderedDict

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import config
from app.api import playback
from app.db import Base, get_db
from app.models import ImageBackup
from app.services import images, image_backups as backups

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jS7sAAAAASUVORK5CYII=')
URL = 'https://cdn.example/cover.png'


@pytest.fixture
def proxy(tmp_path, monkeypatch):
    settings = config.Settings(_env_file=None, database_url=f'sqlite:///{tmp_path.as_posix()}/images.db')
    monkeypatch.setattr(config, 'get_settings', lambda: settings)
    monkeypatch.setattr(images, '_CACHE', OrderedDict())
    replies, requests = [], []
    def handle(request):
        requests.append(request)
        return replies.pop(0)
    client_type = httpx.AsyncClient
    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: client_type(transport=transport, **kwargs))
    app = FastAPI()
    app.include_router(playback.router, prefix='/api')
    engine = create_engine(settings.database_url, connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    app.state.factory = factory
    def session():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = session
    with TestClient(app) as api:
        yield api, replies, requests
    engine.dispose()


@pytest.mark.parametrize('content_type', ['text/html', 'image/jpeg', 'application/json'])
def test_error_pages_are_not_served_as_images_or_cached_and_retry_can_recover(proxy, content_type):
    api, replies, requests = proxy
    replies.append(httpx.Response(200, content=b'<html>temporary access challenge</html>', headers={'content-type': content_type}))
    response = api.get('/api/images/proxy', params={'url': URL})
    assert response.status_code == 502
    assert images.cache_get(URL) is None
    replies.append(httpx.Response(200, content=PNG, headers={'content-type': 'application/octet-stream'}))
    response = api.get('/api/images/proxy', params={'url': URL})
    assert response.status_code == 200 and response.headers['content-type'] == 'image/png'
    assert response.content == PNG
    assert api.get('/api/images/proxy', params={'url': URL}).content == PNG
    assert len(requests) == 2


def test_existing_invalid_memory_and_backup_are_bypassed_and_replaced(proxy):
    api, replies, requests = proxy
    bad_body = b'<!doctype html><html>old cached error</html>'
    images.cache_set(URL, 'image/jpeg', bad_body)
    with api.app.state.factory() as db:
        backups.queue_images(db, [URL])
        db.commit()
        backups.save_queued_image(db, URL, PNG)
        row = db.query(ImageBackup).one()
        images.scraped_image_path(row.local_name).write_bytes(bad_body)
    replies.append(httpx.Response(200, content=PNG, headers={'content-type': 'text/plain'}))
    response = api.get('/api/images/proxy', params={'url': URL})
    assert response.status_code == 200 and response.content == PNG
    assert images.cache_get(URL) == ('image/png', PNG)
    with api.app.state.factory() as db:
        assert backups.read_saved_image(db, URL) == ('image/png', PNG)
    images.cache_remove(URL)
    assert api.get('/api/images/proxy', params={'url': URL}).content == PNG
    assert len(requests) == 1


def test_image_proxy_still_blocks_private_addresses_before_fetching(proxy):
    api, _, requests = proxy
    response = api.get('/api/images/proxy', params={'url': 'http://127.0.0.1/private.png'})
    assert response.status_code == 400 and not requests


def test_svg_response_and_empty_body_are_distinguished(proxy):
    api, replies, _ = proxy
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>'
    replies.append(httpx.Response(200, content=svg, headers={'content-type': 'text/plain'}))
    response = api.get('/api/images/proxy', params={'url': URL})
    assert response.status_code == 200 and response.headers['content-type'] == 'image/svg+xml'
    replies.append(httpx.Response(200, content=b'', headers={'content-type': 'image/png'}))
    assert api.get('/api/images/proxy', params={'url': URL + '?empty=1'}).status_code == 502


def test_inline_error_page_is_not_saved_as_a_scraped_raster_image(proxy):
    value = 'data:image/png;base64,' + base64.b64encode(b'<html>upstream error</html>').decode()
    assert images.store_scraped_image(value) is None


def test_inline_image_uses_the_actual_image_type_when_the_declared_type_is_wrong(proxy):
    value = 'data:image/jpeg;base64,' + base64.b64encode(PNG).decode()
    url = images.store_scraped_image(value)
    assert url.endswith('.png')
    assert images.scraped_image_path(url.rsplit('/', 1)[-1]).read_bytes() == PNG


def test_site_proxy_reuses_the_permanent_backup_with_no_upstream_request(proxy):
    api, _, requests = proxy
    with api.app.state.factory() as db:
        backups.queue_images(db, [URL])
        db.commit()
        backups.save_queued_image(db, URL, PNG)
    response = api.get('/api/images/proxy', params={'url': URL})
    assert response.status_code == 200 and response.content == PNG
    assert not requests


def test_proxy_response_finishes_a_known_backup_without_creating_a_second_store(proxy):
    api, replies, _ = proxy
    with api.app.state.factory() as db:
        backups.queue_images(db, [URL])
        db.commit()
    replies.append(httpx.Response(200, content=PNG))
    assert api.get('/api/images/proxy', params={'url': URL}).content == PNG
    with api.app.state.factory() as db:
        row = db.query(ImageBackup).one()
        assert row.status == 'done'
        path = images.scraped_image_path(row.local_name)
        assert path.read_bytes() == PNG
        assert len(list(path.parent.iterdir())) == 1
        assert not (path.parent.parent / 'image-cache').exists()


def test_anonymous_proxy_urls_are_not_added_to_permanent_library_storage(proxy):
    api, replies, _ = proxy
    replies.append(httpx.Response(200, content=PNG))
    assert api.get('/api/images/proxy', params={'url': URL}).content == PNG
    with api.app.state.factory() as db:
        assert db.query(ImageBackup).count() == 0


@pytest.mark.parametrize('reply', [
    httpx.Response(302, headers={'location': 'http://127.0.0.1/private.png'}),
    httpx.Response(200, content=b'\x89PNG\r\n\x1a\n' + b'x' * (5 * 1024 * 1024)),
])
def test_proxy_and_backup_share_redirect_and_size_limits(proxy, reply):
    api, replies, requests = proxy
    replies.append(reply)
    response = api.get('/api/images/proxy', params={'url': URL})
    assert response.status_code == 502 and len(requests) == 1
    assert images.cache_get(URL) is None


def test_site_proxy_does_not_read_or_promote_retired_disk_cache(proxy):
    api, replies, _ = proxy
    with api.app.state.factory() as db:
        backups.queue_images(db, [URL])
        db.commit()
    from app.config import get_settings
    root = get_settings().data_dir_path
    key = backups.image_key(URL)
    legacy = root / 'image-cache' / key[:2] / key
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(PNG)
    replies.append(httpx.Response(404))
    assert api.get('/api/images/proxy', params={'url': URL}).status_code == 404
    with api.app.state.factory() as db:
        assert db.query(ImageBackup).one().status == 'pending'
    assert not (root / 'scraped-images').exists()
    assert legacy.read_bytes() == PNG
