from __future__ import annotations

import json

from app.api.settings import parse_priority_list
from app.services.metatube import parse_movie_provider_names


def test_parse_movie_providers_dict_keys():
    data = {
        "movie_providers": {
            "JavBus": "https://javbus.com",
            "FANZA": "https://dmm.co.jp",
        },
        "actor_providers": {"Gfriends": "https://x"},
    }
    names = parse_movie_provider_names(data)
    assert names == ["FANZA", "JavBus"]


def test_parse_movie_providers_pascal_case():
    data = {"MovieProviders": {"HEYZO": "https://heyzo.com"}}
    assert parse_movie_provider_names(data) == ["HEYZO"]


def test_parse_movie_providers_list_strings():
    data = {"movie_providers": ["FC2", "JavBus", "FC2"]}
    assert parse_movie_provider_names(data) == ["FC2", "JavBus"]


def test_parse_movie_providers_list_dicts():
    data = {
        "movie_providers": [
            {"name": "AVE"},
            {"provider": "SOD"},
            {"id": "MGS"},
            {},
        ]
    }
    assert parse_movie_provider_names(data) == ["AVE", "MGS", "SOD"]


def test_parse_movie_providers_garbage():
    assert parse_movie_provider_names(None) == []
    assert parse_movie_provider_names([]) == []
    assert parse_movie_provider_names({"actor_providers": {"Gfriends": "x"}}) == []
    assert parse_movie_provider_names({"movie_providers": "nope"}) == []


def test_parse_priority_list():
    assert parse_priority_list(None) == []
    assert parse_priority_list("") == []
    assert parse_priority_list('["JavBus","FANZA"]') == ["JavBus", "FANZA"]
    assert parse_priority_list(["A", "A", " B "]) == ["A", "B"]
    assert parse_priority_list("not-json") == []
    assert parse_priority_list("{}") == []
    long = "x" * 100
    assert parse_priority_list([long, "ok"]) == ["ok"]
