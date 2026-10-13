"""The front page's list of stored games (backend/app/shelf.py, steam.fetch_app_details and GET /games).
Steam is faked."""

import pytest

from app.shelf import FALLBACK_IMAGE
from app.steam import SteamError, fetch_app_details
from tests.helpers import FakeResponse, add_review, app_details


def test_lists_stored_games_with_their_split_most_reviews_first(client, conn, fake_steam):
    add_review(conn, 1, app_id=620, label="positive")
    add_review(conn, 2, app_id=730, label="positive")
    add_review(conn, 3, app_id=730, label="negative")
    add_review(conn, 4, app_id=730, label="neutral")
    add_review(conn, 5, app_id=730, label="positive")
    fake_steam.responses = [app_details(730, "Counter-Strike 2"), app_details(620, "Portal 2")]

    body = client.get("/games").json()

    assert body["total_reviews"] == 5
    assert body["games"] == [
        {"app_id": 730, "name": "Counter-Strike 2", "image_url": "https://img.example.test/header.jpg",
         "total_reviews": 4, "negative_pct": 25.0, "neutral_pct": 25.0, "positive_pct": 50.0},
        {"app_id": 620, "name": "Portal 2", "image_url": "https://img.example.test/header.jpg",
         "total_reviews": 1, "negative_pct": 0.0, "neutral_pct": 0.0, "positive_pct": 100.0},
    ]
    assert fake_steam.calls[0]["appids"] == 730


def test_names_are_looked_up_once_then_kept(client, conn, fake_steam):
    add_review(conn, 1)
    fake_steam.responses = [app_details(620, "Portal 2")]
    client.get("/games")
    assert client.get("/games").json()["games"][0]["name"] == "Portal 2"
    assert len(fake_steam.calls) == 1  # the second list came from the database


def test_a_failed_lookup_still_lists_the_game_and_tries_again_next_time(client, conn, fake_steam):
    add_review(conn, 1)
    fake_steam.responses = [FakeResponse(503)] * 2 + [app_details(620, "Portal 2")]
    game = client.get("/games").json()["games"][0]
    assert (game["name"], game["image_url"]) == (None, FALLBACK_IMAGE.format(app_id=620))
    assert client.get("/games").json()["games"][0]["name"] == "Portal 2"


def test_after_one_failure_the_other_lookups_are_skipped(client, conn, fake_steam):
    add_review(conn, 1, app_id=620)
    add_review(conn, 2, app_id=730)
    fake_steam.responses = [FakeResponse(503)] * 2
    assert [g["name"] for g in client.get("/games").json()["games"]] == [None, None]
    assert len(fake_steam.calls) == 2  # both retries for the first game, nothing for the second


def test_a_game_steam_has_no_page_for_has_no_name(client, conn, fake_steam):
    add_review(conn, 1)
    fake_steam.responses = [FakeResponse(payload={"620": {"success": False}})] * 2
    assert client.get("/games").json()["games"][0]["name"] is None
    client.get("/games")
    assert len(fake_steam.calls) == 2  # not saved, so it's asked again


def test_unscored_reviews_and_no_games(client, conn, fake_steam):
    add_review(conn, 1, label=None, compound=None)
    assert client.get("/games").json() == {"total_reviews": 0, "games": []}
    assert fake_steam.calls == []


@pytest.mark.parametrize("payload", [{}, {"620": "nope"}, {"620": {"success": True, "data": {}}}, {"620": {"success": True}}])
def test_app_details_in_an_unexpected_shape(fake_steam, payload):
    fake_steam.responses = [FakeResponse(payload=payload)]
    assert fetch_app_details(620) is None


def test_app_details_that_are_not_json(fake_steam):
    fake_steam.responses = [FakeResponse(200)] * 2
    with pytest.raises(SteamError):
        fetch_app_details(620)
