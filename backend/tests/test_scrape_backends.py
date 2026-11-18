import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db import Base
from app.models import Library, MediaItem
from app.services import scrape


@pytest.fixture
def metadata(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, database_url=f'sqlite:///{tmp_path.as_posix()}/metadata.db',
        auto_translate=False, scrape_source='metatube',
        scrape_source_priority='["metatube","stash","stashscrapers"]',
        metatube_provider_priority='["MetaFirst"]', stash_scraper_priority='["StashFirst"]',
        stashscrapers_scraper_priority='["RestFirst"]')
    monkeypatch.setattr(scrape, 'get_settings', lambda: settings)
    engine = create_engine(settings.database_url)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as db:
        lib = Library(name='Fixture', path='local', type='local')
        db.add(lib)
        db.flush()
        item = MediaItem(library_id=lib.id, filename='ABC-123-C.mp4', path='local/ABC-123-C.mp4',
            source_type='local', number='ABC-123-C', title='Original title')
        db.add(item)
        db.commit()
        yield db, item, settings
    engine.dispose()


def lookup(monkeypatch, outcomes):
    calls = []

    async def fake(settings, query, filename, provider, url):
        source = settings.scrape_source
        calls.append((source, scrape._priority_list_from_settings(settings), query, filename, provider, url))
        value = outcomes.get(source)
        if isinstance(value, Exception):
            raise value
        if value:
            result = {'provider': source + ':fixture', 'id': '1', 'title': value}
            return object(), result, result
        return None

    monkeypatch.setattr(scrape, '_lookup_movie', fake)
    return calls


def test_backend_fallback_stops_on_first_hit_and_uses_each_backends_priorities(metadata, monkeypatch):
    db, item, settings = metadata
    calls = lookup(monkeypatch, {'stash': 'Matched title', 'stashscrapers': 'Must not query'})
    assert asyncio.run(scrape.scrape_media_item(db, item))
    assert [(call[0], call[1]) for call in calls] == [('metatube', ['MetaFirst']), ('stash', ['StashFirst'])]
    assert all(call[2:4] == ('ABC-123-C', 'ABC-123-C.mp4') for call in calls)
    assert item.title == 'Matched title' and item.provider == 'stash:fixture'
    assert item.subtitle_flag == 'C' and item.scraped_at
    assert settings.scrape_source == 'metatube'


def test_backend_failure_continues_and_total_miss_preserves_metadata(metadata, monkeypatch):
    db, item, _ = metadata
    calls = lookup(monkeypatch, {'metatube': scrape.MetaTubeError('Unavailable')})
    assert not asyncio.run(scrape.scrape_media_item(db, item))
    assert [call[0] for call in calls] == ['metatube', 'stash', 'stashscrapers']
    db.refresh(item)
    assert item.title == 'Original title' and item.scraped_at is None


@pytest.mark.parametrize('kwargs', [
    {'source_override': 'metatube'}, {'provider_override': 'Chosen'}, {'provider_override': ''},
    {'url_override': 'https://source.example/scene/1'},
])
def test_explicit_selection_never_falls_through_to_other_backends(metadata, monkeypatch, kwargs):
    db, item, _ = metadata
    calls = lookup(monkeypatch, {'stash': 'Must not query'})
    assert not asyncio.run(scrape.scrape_media_item(db, item, **kwargs))
    assert [call[0] for call in calls] == ['metatube']


def test_explicit_backend_overrides_global_first_backend(metadata, monkeypatch):
    db, item, settings = metadata
    calls = lookup(monkeypatch, {'stashscrapers': 'Explicit title'})
    assert asyncio.run(scrape.scrape_media_item(db, item, source_override='stashscrapers'))
    assert [call[0] for call in calls] == ['stashscrapers']
    assert settings.scrape_source == 'metatube'


def test_empty_backend_order_uses_only_current_default(metadata, monkeypatch):
    db, item, settings = metadata
    settings.scrape_source_priority = ''
    calls = lookup(monkeypatch, {'stash': 'Must not query'})
    assert not asyncio.run(scrape.scrape_media_item(db, item))
    assert [call[0] for call in calls] == ['metatube']
