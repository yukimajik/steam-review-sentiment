"""GET /games/{app_id}/offtopic: periods Valve flagged as off-topic review activity (Steam is faked)."""

import time

import pytest

from app import offtopic
from tests.helpers import FakeResponse, review_chart, review_counts

APRIL_3_2019 = 1554249600
APRIL_15_2019 = 1555286400


@pytest.fixture(autouse=True)
def empty_cache():
    offtopic.clear_cache()  # each test starts without cached answers
    yield
    offtopic.clear_cache()


def test_periods_with_the_reviews_they_leave_out(client, fake_steam):
    fake_steam.responses = [
        review_chart([(0, APRIL_3_2019, APRIL_15_2019), (7, APRIL_3_2019, APRIL_15_2019)]),  # type 7: not off-topic
        review_counts(10, 2),     # what Steam counts by default
        review_counts(4090, 1928),  # including off-topic reviews
    ]

    response = client.get("/games/49520/offtopic")

    assert response.status_code == 200
    body = response.json()
    assert body["app_id"] == 49520
    assert body["periods"] == [{
        "start": "2019-04-03T00:00:00Z", "end": "2019-04-15T00:00:00Z",
        "reviews_left_out": 4080, "negative_left_out": 1926, "still_flagged": False,
    }]
    chart, default, everything = fake_steam.calls
    assert chart == {"l": "english", "review_score_preference": 0}
    assert (default["start_date"], default["end_date"]) == (APRIL_3_2019, APRIL_15_2019)
    assert default["filter_offtopic_activity"] == 1 and everything["filter_offtopic_activity"] == 0
    assert default["language"] == everything["language"] == "english"


def test_game_never_flagged(client, fake_steam):
    fake_steam.responses = [review_chart([])]
    body = client.get("/games/620/offtopic").json()
    assert body["periods"] == []
    assert len(fake_steam.calls) == 1  # no counts to ask for


def test_period_still_going_on(client, fake_steam):
    now = int(time.time())  # Steam reports an ongoing period as ending at the moment of the request
    fake_steam.responses = [review_chart([(0, now - 86400 * 20, now)]), review_counts(0, 0), review_counts(681, 427)]
    period = client.get("/games/949230/offtopic").json()["periods"][0]
    assert period["still_flagged"] is True
    assert (period["reviews_left_out"], period["negative_left_out"]) == (681, 427)


def test_answers_are_cached(client, fake_steam):
    fake_steam.responses = [review_chart([])]
    client.get("/games/620/offtopic")
    second = client.get("/games/620/offtopic")
    assert second.status_code == 200
    assert len(fake_steam.calls) == 1  # the second answer came from the cache


@pytest.mark.parametrize("steam_answer", [
    FakeResponse(404),                                          # Steam refuses
    FakeResponse(payload={"success": 2}),                       # Steam says it failed
    FakeResponse(payload="<html>"),                             # not the shape we expect
])
def test_chart_failure_returns_502(client, fake_steam, steam_answer):
    fake_steam.responses = [steam_answer]
    response = client.get("/games/620/offtopic")
    assert response.status_code == 502


def test_counts_failure_returns_502(client, fake_steam):
    fake_steam.responses = [review_chart([(0, APRIL_3_2019, APRIL_15_2019)]), FakeResponse(payload={"success": 1})]
    assert client.get("/games/49520/offtopic").status_code == 502


def test_rate_limited_returns_429(client, fake_steam):
    fake_steam.responses = [FakeResponse(429)] * 3
    response = client.get("/games/620/offtopic")
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"


def test_rejects_bad_app_id(client):
    assert client.get("/games/0/offtopic").status_code == 422
