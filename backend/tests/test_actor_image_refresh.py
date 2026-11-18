import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import config
from app.api import actors as actors_api
from app.db import Base, get_db
from app.deps import require_auth
from app.models import Actor, ImageBackup
from app.services import metatube, scrape, stash


OLD = 'https://images.example/old.jpg'
NEW = 'https://images.example/new.jpg'


@pytest.fixture
def actor_api(tmp_path, monkeypatch):
    settings = config.Settings(_env_file=None, database_url=f'sqlite:///{tmp_path.as_posix()}/actors.db',
        scrape_source='metatube', metatube_token='fixture', stash_base_url='http://stash.example',
        image_proxy_mode='site', image_site_base_url='')
    for module in (config, metatube, scrape, stash):
        monkeypatch.setattr(module, 'get_settings', lambda: settings)
    engine = create_engine(settings.database_url, connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    app = FastAPI()
    app.include_router(actors_api.router, prefix='/api')

    def session():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = session
    app.dependency_overrides[require_auth] = lambda: {}
    with TestClient(app) as api:
        yield api, factory
    engine.dispose()


def seed(factory, **overrides):
    with factory() as db:
        actor = Actor(**{'name': 'Fixture actor', 'provider': 'stash:Source',
            'provider_id': 'actor-id', 'image_url': OLD, **overrides})
        db.add(actor)
        db.commit()
        return actor.id


def test_actor_image_refresh_uses_original_source_and_commits_image(actor_api, monkeypatch):
    api, factory = actor_api
    actor_id = seed(factory)
    calls = []

    async def get_actor(_, provider, actor_id):
        calls.append((provider, actor_id))
        return {'provider': provider, 'id': actor_id, 'images': [NEW]}

    monkeypatch.setattr(stash.StashClient, 'get_actor', get_actor)
    response = api.post(f'/api/actors/{actor_id}/rescrape-image')
    assert response.status_code == 200, response.text
    assert calls == [('stash:Source', 'actor-id')]
    with factory() as db:
        assert db.get(Actor, actor_id).image_url == NEW
        assert db.query(ImageBackup).filter_by(url=NEW).one().status == 'pending'
    assert api.get(f'/api/actors/{actor_id}').json()['image_url'] == response.json()['image_url']


@pytest.mark.parametrize('old_image', [OLD, None])
def test_actor_image_miss_preserves_existing_image(actor_api, monkeypatch, old_image):
    api, factory = actor_api
    actor_id = seed(factory, image_url=old_image)

    async def miss(*args):
        return {}

    monkeypatch.setattr(stash.StashClient, 'get_actor', miss)
    response = api.post(f'/api/actors/{actor_id}/rescrape-image')
    assert response.status_code == 502
    with factory() as db:
        assert db.get(Actor, actor_id).image_url == old_image
        assert db.query(ImageBackup).count() == 0


def test_actor_image_refresh_returns_canonical_actor_after_identity_merge(actor_api, monkeypatch):
    api, factory = actor_api
    draft_id = seed(factory, provider=None, provider_id=None)
    canonical_id = seed(factory, provider='Gfriends', provider_id='canonical')

    async def search_actor(_, name):
        return [{'provider': 'Gfriends', 'id': 'canonical', 'images': [NEW]}]

    monkeypatch.setattr(metatube.MetaTubeClient, 'search_actor', search_actor)
    response = api.post(f'/api/actors/{draft_id}/rescrape-image')
    assert response.status_code == 200, response.text
    assert response.json()['id'] == canonical_id
    with factory() as db:
        assert db.get(Actor, draft_id) is None
        assert db.get(Actor, canonical_id).image_url == NEW
