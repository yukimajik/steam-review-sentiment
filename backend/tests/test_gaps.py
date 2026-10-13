"""Filling the weekly chart's gaps (backend/app/gaps.py and POST /games/{app_id}/trend/fill). Steam is faked."""

from datetime import date, datetime, timedelta, timezone

import pytest

from app import gaps, steam, updates
from tests.helpers import FakeResponse, add_review, steam_page, steam_review

TODAY = date(2026, 10, 12)  # a Monday: the week of Oct 5 is over, the week of Oct 12 isn't
SEP_7, SEP_14, SEP_21, SEP_28 = date(2026, 9, 7), date(2026, 9, 14), date(2026, 9, 21), date(2026, 9, 28)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(updates, "today", lambda: TODAY)
    # Most tests are about the stored range; the look-back gets its own test
    monkeypatch.setattr(gaps, "LOOKBACK_WEEKS", 0)


def monday(day: date, hour: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc)


def add_full_week(conn, week: date, first_id: int, app_id=620):
    """30 reviews: enough for the week to be solid on the chart."""
    for i in range(gaps.MIN_REVIEWS):
        add_review(conn, first_id + i, app_id=app_id, created_at=monday(week, 12))


def add_weeks_with_gaps(conn):
    """Full weeks of Sep 7 and Sep 28, none in the two weeks between."""
    add_full_week(conn, SEP_7, 1)
    add_full_week(conn, SEP_28, 100)


def review_in(week: date, review_id: int):
    return steam_review(review_id, "Still great", timestamp=int(monday(week, 12).timestamp()))


def test_trend_counts_the_weeks_to_fill(client, conn):
    add_weeks_with_gaps(conn)
    conn.execute("INSERT INTO gap_weeks (app_id, week) VALUES (620, %s)", (SEP_21,))  # filled, Steam had none
    conn.commit()
    assert client.get("/games/620/trend").json()["weeks_to_fill"] == 1


def test_weeks_with_few_reviews_count_too(conn):
    add_full_week(conn, SEP_7, 1)
    add_review(conn, 50, created_at=monday(SEP_14, 12))  # 1 review: maybe only part of the week is stored
    add_full_week(conn, SEP_21, 100)
    assert gaps.weeks_to_fill(conn, 620, TODAY) == [SEP_14]


def test_the_current_week_is_left_alone(conn):
    add_full_week(conn, SEP_28, 1)
    add_review(conn, 50, created_at=monday(TODAY, 12))  # this week isn't over yet
    assert gaps.weeks_to_fill(conn, 620, TODAY) == [date(2026, 10, 5)]  # the empty week before it still counts


def test_the_past_year_is_filled_back_from_the_first_stored_week(conn, monkeypatch):
    monkeypatch.setattr(gaps, "LOOKBACK_WEEKS", 4)  # 4 weeks before Oct 12: from Sep 14
    add_full_week(conn, SEP_28, 1)
    add_full_week(conn, date(2026, 10, 5), 100)
    assert gaps.weeks_to_fill(conn, 620, TODAY) == [SEP_21, SEP_14]


def test_a_game_stored_further_back_than_a_year_keeps_its_own_range(conn, monkeypatch):
    monkeypatch.setattr(gaps, "LOOKBACK_WEEKS", 2)  # from Sep 28, later than the first stored week
    add_full_week(conn, SEP_7, 1)
    add_full_week(conn, SEP_28, 100)
    assert gaps.weeks_to_fill(conn, 620, TODAY) == [SEP_21, SEP_14]


def test_only_weeks_inside_the_stored_range_count(conn):
    add_full_week(conn, SEP_7, 1)
    add_full_week(conn, SEP_14, 100)
    add_review(conn, 500, app_id=730, created_at=monday(SEP_28, 12))  # another game's reviews don't count
    assert gaps.weeks_to_fill(conn, 620, TODAY) == []


def test_fill_asks_steam_for_each_week_newest_first(client, conn, fake_steam):
    add_weeks_with_gaps(conn)
    fake_steam.responses = [steam_page([review_in(SEP_21, 500)]), steam_page([review_in(SEP_14, 501)])]

    body = client.post("/games/620/trend/fill").json()

    assert body == {"app_id": 620, "filled_weeks": 2, "new_reviews": 2, "remaining": 0}
    assert [(c["start_date"], c["end_date"]) for c in fake_steam.calls] == [
        (int(monday(SEP_21).timestamp()), int(monday(SEP_28).timestamp()) - 1),  # the whole week, in UTC
        (int(monday(SEP_14).timestamp()), int(monday(SEP_21).timestamp()) - 1),
    ]
    assert fake_steam.sleeps == [steam.DELAY_BETWEEN_PAGES]  # a pause between the 2 weeks
    labels = conn.execute("SELECT sentiment_label FROM reviews WHERE recommendation_id IN (500, 501)").fetchall()
    assert len(labels) == 2 and all(label is not None for (label,) in labels)  # scored
    assert client.get("/games/620/trend").json()["weeks_to_fill"] == 0  # still under 30, but done


def test_a_week_steam_has_no_reviews_for_is_not_asked_about_again(client, conn, fake_steam):
    add_weeks_with_gaps(conn)
    fake_steam.responses = [steam_page([]), steam_page([])]
    assert client.post("/games/620/trend/fill").json()["new_reviews"] == 0

    trend = client.get("/games/620/trend").json()
    weeks_with_reviews = sum(month["weeks"] for month in trend["months"])
    assert (weeks_with_reviews, trend["weeks_to_fill"]) == (2, 0)  # the gap stays, but is done
    assert client.post("/games/620/trend/fill").json() == {
        "app_id": 620, "filled_weeks": 0, "new_reviews": 0, "remaining": 0}
    assert len(fake_steam.calls) == 2  # the second fill didn't ask Steam


def test_fill_again_continues_with_the_next_weeks(client, conn, fake_steam, monkeypatch):
    monkeypatch.setattr(gaps, "WEEKS_PER_REQUEST", 1)
    add_weeks_with_gaps(conn)
    fake_steam.responses = [steam_page([]), steam_page([])]
    assert client.post("/games/620/trend/fill").json()["remaining"] == 1
    assert client.post("/games/620/trend/fill").json()["remaining"] == 0
    assert fake_steam.calls[1]["start_date"] == int(monday(SEP_14).timestamp())


def test_fill_failing_midway_keeps_the_weeks_already_done(client, conn, fake_steam):
    add_weeks_with_gaps(conn)
    fake_steam.responses = [steam_page([review_in(SEP_21, 500)]), FakeResponse(404)]
    response = client.post("/games/620/trend/fill")
    assert response.status_code == 502
    assert conn.execute("SELECT week FROM gap_weeks").fetchall() == [(SEP_21,)]
    assert conn.execute("SELECT sentiment_label FROM reviews WHERE recommendation_id = 500").fetchone()[0] is not None
    assert gaps.weeks_to_fill(conn, 620, TODAY) == [SEP_14]


def test_fill_when_steam_rate_limits_midway(client, conn, fake_steam):
    add_weeks_with_gaps(conn)
    fake_steam.responses = [steam_page([])] + [FakeResponse(429)] * 3
    response = client.post("/games/620/trend/fill")
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"
    assert "try again in a minute" in response.json()["detail"]
    assert gaps.weeks_to_fill(conn, 620, TODAY) == [SEP_14]  # the first week is kept for next time


def test_fill_notices_when_steam_ignores_the_week(client, conn, fake_steam):
    add_weeks_with_gaps(conn)
    fake_steam.responses = [steam_page([review_in(SEP_28 + timedelta(days=7), 500)])]  # a review from another week
    response = client.post("/games/620/trend/fill")
    assert response.status_code == 502
    assert "ignored the date range for app 620 in the week of 2026-09-21" in response.json()["detail"]


def test_fill_unknown_game_returns_404(client):
    assert client.post("/games/620/trend/fill").status_code == 404
