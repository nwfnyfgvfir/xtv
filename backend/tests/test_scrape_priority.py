from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from app.services.scrape import _pick_best, _priority_list_from_settings, _search_with_chain


class FakeClient:
    def __init__(self, responses: dict[tuple[str, bool], list[dict[str, Any]]]):
        self.responses = responses
        self.calls: list[tuple[str, str, bool]] = []

    async def search_movie(self, q: str, provider: str = "", fallback: bool = True):
        self.calls.append((q, provider, fallback))
        return list(self.responses.get((provider, fallback), []))


def test_priority_list_from_settings_json():
    s = SimpleNamespace(metatube_provider_priority='["JavBus", "FANZA"]')
    assert _priority_list_from_settings(s) == ["JavBus", "FANZA"]


def test_priority_list_from_settings_list():
    s = SimpleNamespace(metatube_provider_priority=["A", "A", "B"])
    assert _priority_list_from_settings(s) == ["A", "B"]


def test_pick_best_exact_number():
    results = [
        {"number": "SSIS-001", "provider": "X"},
        {"number": "ABC-123", "provider": "Y"},
    ]
    best = _pick_best(results, "ABC-123")
    assert best and best["provider"] == "Y"


def test_chain_stops_on_first_hit():
    client = FakeClient(
        {
            ("A", False): [],
            ("B", False): [{"number": "SSIS-001", "id": "1", "provider": "B"}],
            ("", True): [{"number": "SSIS-001", "id": "2", "provider": "Z"}],
        }
    )
    results = asyncio.run(
        _search_with_chain(
            client,  # type: ignore[arg-type]
            "SSIS-001",
            chain=["A", "B", "C"],
            use_fallback=True,
            force_auto=False,
        )
    )
    assert _pick_best(results, "SSIS-001")["provider"] == "B"
    assert client.calls == [
        ("SSIS-001", "A", False),
        ("SSIS-001", "B", False),
    ]


def test_chain_fallback_when_all_miss():
    client = FakeClient(
        {
            ("A", False): [],
            ("B", False): [],
            ("", True): [{"number": "SSIS-001", "id": "9", "provider": "AUTO"}],
        }
    )
    results = asyncio.run(
        _search_with_chain(
            client,  # type: ignore[arg-type]
            "SSIS-001",
            chain=["A", "B"],
            use_fallback=True,
            force_auto=False,
        )
    )
    assert _pick_best(results, "SSIS-001")["provider"] == "AUTO"
    assert client.calls[-1] == ("SSIS-001", "", True)


def test_chain_no_fallback_when_disabled():
    client = FakeClient({("A", False): []})
    results = asyncio.run(
        _search_with_chain(
            client,  # type: ignore[arg-type]
            "SSIS-001",
            chain=["A"],
            use_fallback=False,
            force_auto=False,
        )
    )
    assert results == []
    assert client.calls == [("SSIS-001", "A", False)]


def test_force_auto_ignores_chain():
    client = FakeClient({("", True): [{"number": "X", "id": "1"}]})
    asyncio.run(
        _search_with_chain(
            client,  # type: ignore[arg-type]
            "X",
            chain=["A", "B"],
            use_fallback=True,
            force_auto=True,
        )
    )
    assert client.calls == [("X", "", True)]


def test_empty_chain_auto():
    client = FakeClient({("", True): [{"number": "X", "id": "1"}]})
    asyncio.run(
        _search_with_chain(
            client,  # type: ignore[arg-type]
            "X",
            chain=[],
            use_fallback=True,
            force_auto=False,
        )
    )
    assert client.calls == [("X", "", True)]
