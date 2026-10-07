"""API endpoints, run against the test database with Steam faked (see conftest.py)."""

from datetime import datetime, timezone

import psycopg
import pytest

from app.main import app, get_conn
from tests.helpers import FakeResponse, add_review, steam_page, steam_review


def day(month, d=15):
    return datetime(2026, month, d, tzinfo=timezone.utc)


# ---------- POST /games/{app_id}/fetch ----------

def test_fetch_saves_and_scores_reviews(client, conn, fake_steam):
    fake_steam.responses = [
        steam_page([steam_review(1, "I love this game, amazing"),
                    steam_review(2, "Terrible. Broken and boring.", voted_up=False)], cursor="A"),
        steam_page([steam_review(3, "👍👍👍")], cursor="B"),  # no words the model knows
        steam_page([], cursor="C"),
    ]
    response = client.post("/games/620/fetch")

    assert response.status_code == 200
    assert response.json() == {"app_id": 620, "fetched": 3, "new": 3, "scored": 3}
    labels = conn.execute("SELECT recommendation_id, sentiment_label FROM reviews ORDER BY 1").fetchall()
    assert labels == [(1, "positive"), (2, "negative"), (3, "neutral")]


def test_fetching_again_skips_saved_reviews(client, fake_steam):
    fake_steam.responses = [steam_page([steam_review(1)]), steam_page([])] * 2
    client.post("/games/620/fetch")
    response = client.post("/games/620/fetch")
    assert response.json() == {"app_id": 620, "fetched": 1, "new": 0, "scored": 0}


def test_fetch_respects_max_reviews(client, fake_steam):
    fake_steam.responses = [steam_page([steam_review(1), steam_review(2), steam_review(3)])]
    response = client.post("/games/620/fetch?max_reviews=2")
    assert response.json()["fetched"] == 2


def test_fetch_game_with_no_reviews_returns_404(client, fake_steam):
    fake_steam.responses = [steam_page([])]
    response = client.post("/games/999999999/fetch")
    assert response.status_code == 404
    assert "may not exist, or it has no reviews yet" in response.json()["detail"]


def test_fetch_when_steam_fails_returns_502(client, fake_steam):
    fake_steam.responses = [FakeResponse(503)] * 3
    response = client.post("/games/620/fetch")
    assert response.status_code == 502
    assert "Steam API error" in response.json()["detail"]


def test_fetch_failing_midway_keeps_and_scores_saved_pages(client, conn, fake_steam):
    fake_steam.responses = [steam_page([steam_review(1)], cursor="A"), FakeResponse(404)]
    response = client.post("/games/620/fetch")
    assert response.status_code == 502
    assert conn.execute("SELECT sentiment_label FROM reviews").fetchall() == [("positive",)]


@pytest.mark.parametrize("url", [
    "/games/620/fetch?max_reviews=0",
    "/games/620/fetch?max_reviews=5001",
    "/games/0/fetch",
    "/games/3000000000/fetch",
    "/games/abc/fetch",
])
def test_fetch_rejects_bad_input(client, url):
    assert client.post(url).status_code == 422


# ---------- GET /games/{app_id}/summary ----------

def test_summary(client, conn):
    # (Steam vote, VADER label) for 9 reviews: 6 Recommended, 3 Not recommended.
    # Chosen so every expected percentage is different, so a mix-up can't pass by coincidence.
    votes_and_labels = ([(True, "positive")] * 3 + [(True, "neutral")] * 2 + [(True, "negative")]
                        + [(False, "positive")] + [(False, "negative")] * 2)
    for review_id, (voted_up, label) in enumerate(votes_and_labels, start=1):
        add_review(conn, review_id, voted_up=voted_up, label=label)
    add_review(conn, 100, app_id=730, label="negative")   # another game: ignored
    add_review(conn, 101, label=None, compound=None)     # not scored yet: ignored

    response = client.get("/games/620/summary")

    assert response.status_code == 200
    assert response.json() == {
        "app_id": 620,
        "total_reviews": 9,
        "positive_pct": 44.4,    # 4 of 9
        "neutral_pct": 22.2,     # 2 of 9
        "negative_pct": 33.3,    # 3 of 9
        "agreement_pct": 55.6,   # 3 positive + Recommended, 2 negative + Not recommended: 5 of 9
        "baseline_pct": 66.7,    # always guessing Recommended: 6 of 9
    }


def test_summary_unknown_game_returns_404(client):
    response = client.get("/games/620/summary")
    assert response.status_code == 404
    assert "POST /games/620/fetch first" in response.json()["detail"]


# ---------- GET /games/{app_id}/trend ----------

def test_trend_averages_by_month(client, conn):
    add_review(conn, 1, compound=0.5, created_at=day(7, 1))
    add_review(conn, 2, compound=-0.1, created_at=day(7, 31))
    add_review(conn, 3, compound=0.3, created_at=day(8))

    response = client.get("/games/620/trend")

    assert response.status_code == 200
    assert response.json() == {"app_id": 620, "months": [
        {"month": "2026-07", "avg_compound": 0.2, "review_count": 2},
        {"month": "2026-08", "avg_compound": 0.3, "review_count": 1},
    ]}


def test_trend_unknown_game_returns_404(client):
    assert client.get("/games/620/trend").status_code == 404


# ---------- GET /games/{app_id}/reviews ----------

def test_reviews_are_paginated_newest_first(client, conn):
    for review_id in range(1, 6):  # review 5 is the newest
        add_review(conn, review_id, created_at=day(review_id + 1))

    first = client.get("/games/620/reviews?page_size=2").json()
    last = client.get("/games/620/reviews?page_size=2&page=3").json()
    past_end = client.get("/games/620/reviews?page_size=2&page=4").json()

    assert [r["recommendation_id"] for r in first["items"]] == [5, 4]
    assert first["total"] == 5
    assert [r["recommendation_id"] for r in last["items"]] == [1]
    assert past_end["items"] == [] and past_end["total"] == 5


def test_reviews_sentiment_filter(client, conn):
    add_review(conn, 1, label="positive")
    add_review(conn, 2, label="negative", compound=-0.6, text="awful")
    add_review(conn, 3, label="negative", compound=-0.4)

    body = client.get("/games/620/reviews?sentiment=negative").json()

    assert body["total"] == 2
    assert {r["recommendation_id"] for r in body["items"]} == {2, 3}
    review_2 = next(r for r in body["items"] if r["recommendation_id"] == 2)
    assert review_2["review_text"] == "awful"
    assert review_2["sentiment_compound"] == pytest.approx(-0.6)


def test_reviews_filter_with_no_matches_is_empty_not_404(client, conn):
    add_review(conn, 1, label="positive")
    response = client.get("/games/620/reviews?sentiment=negative")
    assert response.status_code == 200
    assert response.json()["items"] == []


@pytest.mark.parametrize("query", ["sentiment=angry", "page=0", "page_size=0", "page_size=101"])
def test_reviews_reject_bad_input(client, conn, query):
    add_review(conn, 1)
    assert client.get(f"/games/620/reviews?{query}").status_code == 422


def test_reviews_unknown_game_returns_404(client):
    assert client.get("/games/620/reviews").status_code == 404


# ---------- CORS and database errors ----------

def test_cors_allows_local_frontend(client):
    response = client.options("/games/620/summary", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET",
    })
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_blocks_other_sites(client):
    response = client.options("/games/620/summary", headers={
        "Origin": "https://some-other-site.example", "Access-Control-Request-Method": "GET",
    })
    assert "access-control-allow-origin" not in response.headers


def test_database_down_returns_503(client):
    def broken_conn():
        raise psycopg.OperationalError("connection refused")
        yield  # never reached; makes this a generator like the real get_conn

    app.dependency_overrides[get_conn] = broken_conn
    response = client.get("/games/620/summary")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database is unavailable. Is it running?"}
