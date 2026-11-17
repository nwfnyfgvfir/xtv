import asyncio
from types import SimpleNamespace

from app.services.metatube import MetaTubeClient, MetaTubeError
from app.services.scrape import _pick_best, _priority_list_from_settings, _search_with_chain


class FakeClient(MetaTubeClient):
    def __init__(self, responses, sources=('A', 'B', 'C', 'D')):
        self.responses, self.sources, self.calls = responses, sources, []

    async def search_movie(self, query, provider='', fallback=True):
        self.calls.append((query, provider, fallback))
        value = self.responses.get(provider, [])
        if isinstance(value, Exception):
            raise value
        return value

    async def list_providers(self):
        return {'movie_providers': [{'id': source} for source in self.sources]}


def test_priority_settings_preserve_order_and_deduplicate():
    settings = SimpleNamespace(metatube_provider_priority='["B", "A", "B"]')
    assert _priority_list_from_settings(settings) == ['B', 'A']


def test_priority_stops_after_first_source_result():
    client = FakeClient({'B': [{'provider': 'B', 'number': 'provider-code'}]})
    rows = asyncio.run(_search_with_chain(client, 'original filename', chain=['A', 'B', 'C']))
    assert rows[0]['provider'] == 'B'
    assert client.calls == [('original filename', 'A', False), ('original filename', 'B', False)]


def test_priority_sources_are_preferences_and_remaining_sources_are_always_tried():
    client = FakeClient({'A': MetaTubeError('fixture failure'), 'D': [{'provider': 'D'}]})
    rows = asyncio.run(_search_with_chain(client, 'FC2-PPV-1066192', chain=['C', 'A', 'B']))
    assert rows[0]['provider'] == 'D'
    assert [call[1] for call in client.calls] == ['C', 'A', 'B', 'D']
    assert all(call[0] == 'FC2-PPV-1066192' and call[2] is False for call in client.calls)


def test_all_sources_can_fail_without_repeating_priority_sources():
    client = FakeClient({}, sources=('A', 'B', 'C', 'D', 'E'))
    assert asyncio.run(_search_with_chain(client, 'query', chain=['B', 'C', 'A'])) == []
    assert [call[1] for call in client.calls] == ['B', 'C', 'A', 'D', 'E']


def test_empty_priority_uses_automatic_source_selection():
    client = FakeClient({'': [{'provider': 'automatic'}]})
    assert asyncio.run(_search_with_chain(client, 'query', chain=[]))[0]['provider'] == 'automatic'
    assert client.calls == [('query', '', True)]


def test_explicit_single_scene_source_remains_targeted():
    client = FakeClient({'B': [{'provider': 'B'}]})
    assert asyncio.run(_search_with_chain(client, 'query', chain=['A'], selected_only=True)) == []
    assert client.calls == [('query', 'A', False)]


def test_provider_result_ranking_does_not_rewrite_source_filename():
    rows = [{'number': 'FC2-1066192', 'provider': 'source'}]
    assert _pick_best(rows, 'FC2-PPV-1066192') is rows[0]
