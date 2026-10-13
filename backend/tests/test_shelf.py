"""The front page's list of stored games and one game's details (backend/app/shelf.py, steam.fetch_app_details,
GET /games and GET /games/{app_id}/details). Steam is faked."""

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


# ---------- GET /games/{app_id}/details ----------

def test_details_of_a_game_are_looked_up_once_then_kept(client, fake_steam):
    fake_steam.responses = [app_details(570, "Dota 2")]
    first = client.get("/games/570/details")
    second = client.get("/games/570/details")
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == {
        "app_id": 570, "name": "Dota 2", "image_url": "https://img.example.test/header.jpg"}
    assert len(fake_steam.calls) == 1  # works without stored reviews; the second answer came from the database


def test_details_reuse_what_the_shelf_looked_up(client, conn, fake_steam):
    add_review(conn, 1)
    fake_steam.responses = [app_details(620, "Portal 2")]
    client.get("/games")
    assert client.get("/games/620/details").json()["name"] == "Portal 2"
    assert len(fake_steam.calls) == 1


def test_details_without_a_cover_use_the_fallback_image(client, fake_steam):
    fake_steam.responses = [FakeResponse(payload={"620": {"success": True, "data": {"name": "Portal 2"}}})]
    assert client.get("/games/620/details").json()["image_url"] == FALLBACK_IMAGE.format(app_id=620)


def test_details_of_a_game_steam_has_no_page_for_return_404(client, fake_steam):
    fake_steam.responses = [FakeResponse(payload={"620": {"success": False}})]
    response = client.get("/games/620/details")
    assert response.status_code == 404
    assert response.json()["detail"] == "Steam has no store page for app 620."


def test_details_when_steam_fails_return_502(client, fake_steam):
    fake_steam.responses = [FakeResponse(503)] * 2 + [app_details(620, "Portal 2")]
    response = client.get("/games/620/details")
    assert response.status_code == 502
    assert "Steam store error" in response.json()["detail"]
    assert client.get("/games/620/details").json()["name"] == "Portal 2"  # nothing was saved, so it tries again


@pytest.mark.parametrize("app_id", ["0", "abc", str(2**31)])
def test_details_with_a_bad_app_id_return_422(client, app_id):
    assert client.get(f"/games/{app_id}/details").status_code == 422
