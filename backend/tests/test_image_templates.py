from urllib.parse import quote

import pytest

from app import config
from app.services import images

REMOTE = 'https://cdn.example/cover.jpg?size=large&name=A+B'
TEMPLATE = 'https://proxy.example/?url={url}'
METATUBE = 'https://mt.example/v1/images/primary/{provider}/{id}?url={url}&quality={quality}'


@pytest.fixture
def settings(monkeypatch):
    value = config.Settings(_env_file=None, image_proxy_mode='site', image_external_proxy_url='')
    monkeypatch.setattr(config, 'get_settings', lambda: value)
    return value


def test_site_proxy_encodes_the_original_and_does_not_wrap_it_twice(settings):
    proxy = '/api/images/proxy?url=' + quote(REMOTE, safe='')
    assert images.site_proxy_url(REMOTE) == proxy
    assert images.site_proxy_url(proxy) == proxy
    assert images.rewrite_image_url(proxy) == proxy
    assert images.original_image_url(proxy) == REMOTE


@pytest.mark.parametrize('template', [TEMPLATE, 'https://proxy.example/image/{url}?key=fixture', METATUBE,
    'https://proxy.example/?image={url}&duplicate={url}'])
def test_all_remote_templates_use_one_renderer_and_unwrap_to_the_original(settings, template):
    settings.image_proxy_mode, settings.image_external_proxy_url = 'external', template
    rendered = images.rewrite_image_url(REMOTE, provider='Source Name', provider_id='A/B 001', quality=85)
    assert quote(REMOTE, safe='') in rendered
    if template == METATUBE:
        assert '/Source%20Name/A%2FB%20001?' in rendered and 'quality=85' in rendered
    assert images.original_image_url(rendered) == REMOTE
    assert images.rewrite_image_url(rendered, provider='Source Name', provider_id='A/B 001', quality=85) == rendered


@pytest.mark.parametrize('template', ['', 'https://proxy.example/', 'file:///tmp/{url}',
    'https://{url}/image', 'https://{provider}/?url={url}', 'https://proxy.example/?url={unknown}',
    'https://proxy.example/?url={url}&extra={bad}', 'https://proxy.example/?url={url}&extra={'])
def test_invalid_templates_fail_explicitly_without_changing_to_the_site_proxy(settings, template):
    settings.image_proxy_mode, settings.image_external_proxy_url = 'external', template
    assert images.remote_proxy_template_error(template)
    assert images.rewrite_image_url(REMOTE) is None


@pytest.mark.parametrize('provider,provider_id', [(None, None), ('stash:Fixture', '1'), ('stashscrapers:Fixture', '2')])
def test_identity_templates_do_not_send_incompatible_ids_but_url_only_templates_work_for_every_source(settings, provider, provider_id):
    settings.image_proxy_mode = 'external'
    settings.image_external_proxy_url = METATUBE
    assert images.rewrite_image_url(REMOTE, provider=provider, provider_id=provider_id) == REMOTE
    settings.image_external_proxy_url = TEMPLATE
    assert images.rewrite_image_url(REMOTE, provider=provider, provider_id=provider_id) == TEMPLATE.replace('{url}', quote(REMOTE, safe=''))


def test_switching_remote_and_site_templates_keeps_the_original_url(settings):
    site = images.rewrite_image_url(REMOTE)
    settings.image_proxy_mode, settings.image_external_proxy_url = 'external', TEMPLATE
    remote = images.rewrite_image_url(site)
    settings.image_proxy_mode = 'site'
    assert images.rewrite_image_url(remote) == site


@pytest.mark.parametrize('url', ['http://127.0.0.1/image.png', 'http://localhost/image.png',
    'http://metadata.google.internal/image.png', 'file:///tmp/image.png'])
def test_private_image_sources_are_rejected(settings, url):
    with pytest.raises(ValueError):
        images.validate_proxy_url(url)
