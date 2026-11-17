import base64
from collections import OrderedDict

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import config
from app.api import playback
from app.services import images

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jS7sAAAAASUVORK5CYII=')
URL = 'https://cdn.example/cover.png'


@pytest.fixture
def proxy(tmp_path, monkeypatch):
    settings = config.Settings(_env_file=None, database_url=f'sqlite:///{tmp_path.as_posix()}/images.db', image_local_cache=True)
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
    with TestClient(app) as api:
        yield api, replies, requests


@pytest.mark.parametrize('content_type', ['text/html', 'image/jpeg', 'application/json'])
def test_error_pages_are_not_served_as_images_or_cached_and_retry_can_recover(proxy, content_type):
    api, replies, requests = proxy
    replies.append(httpx.Response(200, content=b'<html>temporary access challenge</html>', headers={'content-type': content_type}))
    response = api.get('/api/images/proxy', params={'url': URL})
    assert response.status_code == 502
    assert images.cache_get(URL) is None and images.disk_cache_get(URL) is None
    replies.append(httpx.Response(200, content=PNG, headers={'content-type': 'application/octet-stream'}))
    response = api.get('/api/images/proxy', params={'url': URL})
    assert response.status_code == 200 and response.headers['content-type'] == 'image/png'
    assert response.content == PNG
    assert api.get('/api/images/proxy', params={'url': URL}).content == PNG
    assert len(requests) == 2


def test_existing_invalid_memory_and_disk_cache_are_bypassed_and_replaced(proxy):
    api, replies, requests = proxy
    bad_body = b'<!doctype html><html>old cached error</html>'
    images.cache_set(URL, 'image/jpeg', bad_body)
    images.disk_cache_set(URL, 'image/jpeg', bad_body)
    replies.append(httpx.Response(200, content=PNG, headers={'content-type': 'text/plain'}))
    response = api.get('/api/images/proxy', params={'url': URL})
    assert response.status_code == 200 and response.content == PNG
    assert images.cache_get(URL) == ('image/png', PNG)
    assert images.disk_cache_get(URL) == ('image/png', PNG)
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
