"""GET /search: Steam's store search through our backend, with a cache and typo fallback (Steam is faked)."""

import pytest

from app import search
from tests.helpers import FakeResponse, store_item, store_search_page


@pytest.fixture(autouse=True)
def empty_cache():
    search.clear_cache()  # each test starts without cached results
    yield
    search.clear_cache()


def searched_terms(fake_steam):
    return [call["term"] for call in fake_steam.calls]


def test_search_returns_matches(client, fake_steam):
    fake_steam.responses = [store_search_page([store_item(620, "Portal 2"), store_item(400, "Portal")])]

    response = client.get("/search?q=Portal")

    assert response.status_code == 200
    assert response.json() == {
        "query": "portal",
        "matched_query": "portal",
        "results": [
            {"app_id": 620, "name": "Portal 2", "image_url": "https://img.example.test/620.jpg"},
            {"app_id": 400, "name": "Portal", "image_url": "https://img.example.test/400.jpg"},
        ],
    }
    assert fake_steam.calls == [{"term": "portal", "l": "english", "cc": "US"}]


def test_search_skips_packages_and_bundles(client, fake_steam):
    # Their IDs aren't app IDs, so they couldn't be fetched as games
    fake_steam.responses = [store_search_page([
        store_item(620, "Portal 2"), store_item(7932, "Portal Bundle", item_type="bundle"),
        store_item(32, "Portal Pack", item_type="sub"),
    ])]
    results = client.get("/search?q=portal").json()["results"]
    assert [r["app_id"] for r in results] == [620]


def test_repeated_searches_come_from_the_cache(client, fake_steam):
    fake_steam.responses = [store_search_page([store_item(620, "Portal 2")])]
    client.get("/search?q=Portal")
    response = client.get("/search?q=%20%20PORTAL%20")  # same search, different case and spacing
    assert response.json()["results"][0]["app_id"] == 620
    assert len(fake_steam.calls) == 1


def test_cache_expires(client, fake_steam, monkeypatch):
    monkeypatch.setattr(search, "CACHE_SECONDS", 0)
    fake_steam.responses = [store_search_page([store_item(620, "Portal 2")])] * 2
    client.get("/search?q=portal")
    client.get("/search?q=portal")
    assert len(fake_steam.calls) == 2


def test_cache_drops_oldest_entries_when_full(client, fake_steam, monkeypatch):
    monkeypatch.setattr(search, "CACHE_MAX_ENTRIES", 2)
    fake_steam.responses = [store_search_page([store_item(1, "Game")])] * 4
    for q in ["aaa", "bbb", "ccc", "aaa"]:  # "aaa" was pushed out by "ccc", so it's asked again
        client.get(f"/search?q={q}")
    assert searched_terms(fake_steam) == ["aaa", "bbb", "ccc", "aaa"]


def test_typo_fallback_drops_letters_until_something_matches(client, fake_steam):
    fake_steam.responses = [
        store_search_page([]),                                    # "cyberpnk"
        store_search_page([]),                                    # "cyberpn"
        store_search_page([store_item(1091500, "Cyberpunk 2077")]),  # "cyberp"
    ]
    body = client.get("/search?q=cyberpnk").json()
    assert body["query"] == "cyberpnk"
    assert body["matched_query"] == "cyberp"
    assert body["results"][0]["name"] == "Cyberpunk 2077"
    assert searched_terms(fake_steam) == ["cyberpnk", "cyberpn", "cyberp"]


def test_typo_fallback_gives_up_after_three_tries(client, fake_steam):
    fake_steam.responses = [store_search_page([])] * 4
    body = client.get("/search?q=abcdefg").json()
    assert body == {"query": "abcdefg", "matched_query": "abcdefg", "results": []}
    assert searched_terms(fake_steam) == ["abcdefg", "abcdef", "abcde", "abcd"]


def test_typo_fallback_never_goes_below_three_letters(client, fake_steam):
    fake_steam.responses = [store_search_page([])] * 2
    assert client.get("/search?q=abcd").json()["results"] == []
    assert searched_terms(fake_steam) == ["abcd", "abc"]


def test_typo_fallback_trims_a_trailing_space(client, fake_steam):
    fake_steam.responses = [store_search_page([]), store_search_page([store_item(367520, "Hollow Knight")])]
    client.get("/search?q=hollow%20k")
    assert searched_terms(fake_steam) == ["hollow k", "hollow"]  # not "hollow " with a dangling space


@pytest.mark.parametrize("url", ["/search", "/search?q=a", "/search?q=%20%20a%20", "/search?q=" + "x" * 101])
def test_search_rejects_bad_input(client, fake_steam, url):
    assert client.get(url).status_code == 422
    assert fake_steam.calls == []  # Steam is never asked


def test_search_retries_once_then_returns_502(client, fake_steam):
    fake_steam.responses = [FakeResponse(503), FakeResponse(503)]
    response = client.get("/search?q=portal")
    assert response.status_code == 502
    assert "Steam search error" in response.json()["detail"]
    assert len(fake_steam.calls) == 2  # search gives up sooner than fetching (3 tries)
    assert fake_steam.sleeps == [2]


def test_search_waits_out_a_rate_limit(client, fake_steam):
    fake_steam.responses = [FakeResponse(429, headers={"Retry-After": "3"}), store_search_page([store_item(620, "Portal 2")])]
    assert client.get("/search?q=portal").status_code == 200
    assert fake_steam.sleeps == [3]
