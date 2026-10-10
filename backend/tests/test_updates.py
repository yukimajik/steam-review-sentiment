"""Updates from Steam's news and the before/after comparison (backend/app/updates.py, the
news and per-day review requests in steam.py, and the /updates endpoints). Steam is faked."""

from datetime import date, datetime, timedelta, timezone

import pytest

from app import steam, updates
from app.steam import SteamError, fetch_news, fetch_reviews_on_day
from app.updates import biggest_shifts, group_updates, is_update, window_days
from tests.helpers import (
    FakeResponse, add_review, add_update, mark_days_fetched, news_item, news_page, steam_page, steam_review,
)

TODAY = date(2026, 10, 9)


def at(day: date, hour: int = 12) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc)


@pytest.fixture
def fixed_today(monkeypatch):
    monkeypatch.setattr(updates, "today", lambda: TODAY)


# ---------- which posts count as updates (real titles from the stored games' news) ----------

@pytest.mark.parametrize("title", [
    "Black Myth: Wukong 1.0.21.23831 Patch Notes",              # never tagged, but clearly a patch
    "Update Summary (Ver.1.042.00.02)",
    "10.1.2 | Bugfix Patch",
    "Patch 1.6.2f1 - Autumn Breeze",
    "Hotfix #36 Now Live!",
    "PAYDAY 3: Update 3.9.2 Changelog",
    "The Peer-to-Peer update is now live!",
    "Get ready to take on the Elder Dragon, Gogmazios! Free Title Update 4 out now!",
    "Overwatch Reign of Talon - Season 5: A Grim Doctrine Now Live!",
])
def test_update_titles_count(title):
    assert is_update({"title": title, "tags": []})


@pytest.mark.parametrize("title", [
    "PAYDAY 3: Blog Update #50 – Peer-to-Peer Playtest Retrospective",  # a dev blog
    "Community Update #36 A Very Moddy Christmas",
    "Developer Update | Player Intent System",
    "Dev Update | 10.2.0 Perks Update",
    "10.2.0 | PTB Patch Notes",                                        # the test server
    "9.6.0 Patch Notes Preview",
    "NOW TESTING: Steam test build for 9.6.1 issues",
    "Bike Patch - Announcement Post",
    "Introducing Update Ver. 1.041 — Available Wednesday, February 18",  # posted 8 days before the update
    "Update Ver. 1.042 — Maintenance Notice",
    "Vote for Rust! The Steam Awards are now live!",
    "Black Myth: Wukong — 30% Off Coming Soon",
    "LIVESTOCK",  # a real Rust update, but nothing in its title says so: a known miss
])
def test_other_titles_dont_count(title):
    assert not is_update({"title": title, "tags": []})


def test_steams_patchnotes_tag_always_counts():
    assert is_update({"title": "Release Note for 2025/12/16", "tags": ["patchnotes"]})


# ---------- grouping and windows ----------

def post(day: date, gid="1"):
    return {"gid": gid, "title": "Patch", "url": "u", "posted_at": at(day)}


def test_updates_less_than_14_days_after_a_group_start_join_it():
    posts = [post(date(2026, 8, 20), "e"), post(date(2026, 8, 1), "a"), post(date(2026, 8, 5), "b"),
             post(date(2026, 8, 14), "c"), post(date(2026, 8, 15), "d")]  # out of order on purpose
    groups = group_updates(posts)
    assert [g.day for g in groups] == [date(2026, 8, 1), date(2026, 8, 15)]
    assert [[p["gid"] for p in g.posts] for g in groups] == [["a", "b", "c"], ["d", "e"]]


def test_window_is_14_days_each_side_without_the_update_day():
    days = window_days(date(2026, 8, 15))
    assert len(days) == 28
    assert days[0] == date(2026, 8, 1) and days[13] == date(2026, 8, 14)
    assert days[14] == date(2026, 8, 16) and days[-1] == date(2026, 8, 29)
    assert date(2026, 8, 15) not in days


def test_biggest_shifts_ranks_only_ready_updates():
    def result(shift, status="ready"):
        return {"shift": shift, "status": status}
    results = [result(0.1), result(-0.2), result(0.4), result(0.0), result(0.3), result(0.2),
               result(-0.05), result(0.9, "too_few_reviews"), result(-0.9, "too_few_reviews")]
    rises, drops = biggest_shifts(results)
    assert [r["shift"] for r in rises] == [0.4, 0.3, 0.2]   # top 3, largest first
    assert [r["shift"] for r in drops] == [-0.2, -0.05]     # no change (0.0) is neither


# ---------- Steam requests ----------

def test_fetch_news_asks_for_official_posts_only(fake_steam):
    fake_steam.responses = [news_page([news_item(7, "Patch 1.0.1", at(date(2026, 9, 1)), tags=["patchnotes"])])]
    [item] = fetch_news(620)
    assert fake_steam.calls[0]["feeds"] == "steam_community_announcements"
    assert item == {"gid": "7", "title": "Patch 1.0.1", "url": "https://steam.example.test/news/7",
                    "posted_at": at(date(2026, 9, 1)), "tags": ["patchnotes"]}


def test_fetch_news_in_an_unexpected_format(fake_steam):
    fake_steam.responses = [FakeResponse(payload={"something": "else"})]
    with pytest.raises(SteamError, match="unexpected format"):
        fetch_news(620)


def test_reviews_on_day_asks_for_that_day_in_utc(fake_steam):
    day = date(2026, 8, 18)
    fake_steam.responses = [steam_page([steam_review(1, timestamp=int(at(day, 0).timestamp())),
                                        steam_review(2, timestamp=int(at(day, 23).timestamp()))])]
    reviews = fetch_reviews_on_day(620, day)
    params = fake_steam.calls[0]
    assert params["start_date"] == int(at(day, 0).timestamp())
    assert params["end_date"] == int(at(day, 0).timestamp()) + 86399
    assert params["date_range_type"] == "include"
    assert [r["recommendationid"] for r in reviews] == ["1", "2"]


def test_reviews_on_day_drops_reviews_from_other_days(fake_steam):
    day = date(2026, 8, 18)
    fake_steam.responses = [steam_page([steam_review(1, timestamp=int(at(day).timestamp())),
                                        steam_review(2, timestamp=int(at(day + timedelta(days=1)).timestamp()))])]
    assert [r["recommendationid"] for r in fetch_reviews_on_day(620, day)] == ["1"]


def test_reviews_on_day_notices_when_steam_ignores_the_date_range(fake_steam):
    fake_steam.responses = [steam_page([steam_review(1, timestamp=int(at(date(2026, 10, 8)).timestamp()))])]
    with pytest.raises(SteamError, match="ignored the date range"):
        fetch_reviews_on_day(620, date(2026, 8, 18))


def test_a_day_with_no_reviews(fake_steam):
    fake_steam.responses = [steam_page([])]
    assert fetch_reviews_on_day(620, date(2026, 8, 18)) == []


# ---------- GET /games/{app_id}/updates ----------

def add_reviews(conn, first_id, day, count, compound, recommended):
    for i in range(count):
        add_review(conn, first_id + i, created_at=at(day), compound=compound, voted_up=i < recommended)


def test_before_and_after_numbers(client, conn, fixed_today):
    ready = date(2026, 8, 1)
    add_update(conn, "ready", at(ready), "Patch 1.1.0")
    add_update(conn, "hotfix", at(date(2026, 8, 5)), "Hotfix 1.1.1")         # joins the update above
    add_update(conn, "waiting", at(date(2026, 9, 1)), "Patch 1.2.0")         # reviews not fetched yet
    add_update(conn, "recent", at(date(2026, 10, 1)), "Patch 1.3.0")         # its 2 weeks after aren't over
    add_update(conn, "few", at(date(2026, 6, 1)), "Patch 1.0.5")             # too few reviews
    add_update(conn, "old", at(date(2025, 9, 1)), "Patch 0.9")               # over 12 months ago
    mark_days_fetched(conn, window_days(ready) + window_days(date(2026, 6, 1)))

    add_reviews(conn, 1000, ready - timedelta(days=14), 30, compound=0.2, recommended=15)  # first "before" day
    add_reviews(conn, 2000, ready + timedelta(days=14), 30, compound=0.5, recommended=30)  # last "after" day
    add_review(conn, 3000, created_at=at(ready), compound=-1.0)                            # the update's own day
    add_review(conn, 3001, created_at=at(ready - timedelta(days=15)), compound=-1.0)       # outside the windows
    add_review(conn, 3002, created_at=at(ready + timedelta(days=15)), compound=-1.0)
    add_reviews(conn, 4000, date(2026, 5, 25), 2, compound=0.1, recommended=1)

    body = client.get("/games/620/updates").json()

    assert body["window_days"] == 14 and body["min_reviews"] == 30
    assert [(u["day"], u["status"]) for u in body["updates"]] == [
        ("2026-10-01", "too_recent"), ("2026-09-01", "needs_reviews"), ("2026-08-01", "ready"),
        ("2026-06-01", "too_few_reviews"),
    ]
    ready_update = body["updates"][2]
    assert [p["gid"] for p in ready_update["posts"]] == ["ready", "hotfix"]
    assert ready_update["before"] == {"reviews": 30, "avg_score": 0.2, "recommended_pct": 50.0}
    assert ready_update["after"] == {"reviews": 30, "avg_score": 0.5, "recommended_pct": 100.0}
    assert ready_update["shift"] == pytest.approx(0.3)
    assert body["updates"][3]["after"] == {"reviews": 0, "avg_score": None, "recommended_pct": None}
    assert body["updates"][3]["shift"] is None
    assert body["updates"][0]["before"] is None  # too recent: no numbers yet
    assert [u["day"] for u in body["biggest_rises"]] == ["2026-08-01"]
    assert body["biggest_drops"] == []


def test_only_the_10_most_recent_finished_updates_are_listed(client, conn, fixed_today):
    add_review(conn, 1)
    for month in range(1, 10):  # Jan..Sep 2026, 9 updates
        add_update(conn, f"2026-{month}", at(date(2026, month, 1)))
    for month in (10, 11, 12):  # Oct..Dec 2025, all more than 14 days apart
        add_update(conn, f"2025-{month}", at(date(2025, month, 10)))
    days = [u["day"] for u in client.get("/games/620/updates").json()["updates"]]
    assert len(days) == 10
    assert days[0] == "2026-09-01" and days[-1] == "2025-12-10"  # the 2 oldest of 12 are dropped


def test_an_update_is_too_recent_until_its_14th_day_after_is_over(client, conn, fixed_today):
    add_review(conn, 1)
    add_update(conn, "a", at(TODAY - timedelta(days=14)))  # its last "after" day is today
    add_update(conn, "b", at(TODAY - timedelta(days=29)))  # its last "after" day was yesterday
    statuses = [u["status"] for u in client.get("/games/620/updates").json()["updates"]]
    assert statuses == ["too_recent", "needs_reviews"]


def test_updates_for_an_unknown_game(client):
    assert client.get("/games/620/updates").status_code == 404
    assert client.post("/games/620/updates/fetch").status_code == 404


# ---------- POST /games/{app_id}/updates/fetch ----------

NEWS = [
    news_item(2, "Patch 1.2.0", at(date(2026, 9, 1))),
    news_item(3, "Summer Sale!", at(date(2026, 8, 20))),  # not an update
    news_item(1, "Patch 1.1.0", at(date(2026, 8, 1))),
]


def day_pages(first_day_reviews=()):
    """28 days of review pages: the first day has these reviews, the rest none."""
    return [steam_page(list(first_day_reviews))] + [steam_page([]) for _ in range(27)]


def test_fetch_reads_news_then_reviews_around_the_newest_update(client, conn, fake_steam, fixed_today):
    add_review(conn, 1)
    first_day = date(2026, 9, 1) - timedelta(days=14)
    fake_steam.responses = [news_page(NEWS)] + day_pages([steam_review(500, "Great patch", timestamp=int(at(first_day).timestamp()))])

    body = client.post("/games/620/updates/fetch").json()

    assert body == {"app_id": 620, "updates_found": 2, "fetched_day": "2026-09-01", "new_reviews": 1, "remaining": 1}
    assert conn.execute("SELECT gid FROM game_updates ORDER BY gid").fetchall() == [("1",), ("2",)]
    assert conn.execute("SELECT count(*) FROM update_review_days").fetchone()[0] == 28
    assert conn.execute("SELECT sentiment_label FROM reviews WHERE recommendation_id = 500").fetchone()[0] is not None
    assert fake_steam.calls[1]["start_date"] == int(at(first_day, 0).timestamp())
    assert fake_steam.sleeps == [steam.DELAY_BETWEEN_PAGES] * 27  # a pause between the 28 days


def test_fetch_again_continues_with_the_next_update_then_stops(client, conn, fake_steam, fixed_today):
    add_review(conn, 1)
    fake_steam.responses = [news_page(NEWS)] + day_pages() + [news_page(NEWS)] + day_pages() + [news_page(NEWS)]
    assert client.post("/games/620/updates/fetch").json()["fetched_day"] == "2026-09-01"
    second = client.post("/games/620/updates/fetch").json()
    assert (second["fetched_day"], second["remaining"]) == ("2026-08-01", 0)
    third = client.post("/games/620/updates/fetch").json()
    assert (third["fetched_day"], third["remaining"]) == (None, 0)
    assert fake_steam.responses == []  # the third call only read the news


def test_fetch_skips_days_already_fetched(client, conn, fake_steam, fixed_today):
    add_review(conn, 1)
    mark_days_fetched(conn, window_days(date(2026, 9, 1))[:14])  # the 14 days before are done
    fake_steam.responses = [news_page(NEWS)] + [steam_page([]) for _ in range(14)]
    assert client.post("/games/620/updates/fetch").json()["fetched_day"] == "2026-09-01"
    assert len(fake_steam.calls) == 1 + 14


def test_fetch_failing_midway_keeps_the_days_already_done(client, conn, fake_steam, fixed_today):
    add_review(conn, 1)
    first_day = date(2026, 9, 1) - timedelta(days=14)
    fake_steam.responses = [news_page(NEWS),
                            steam_page([steam_review(500, timestamp=int(at(first_day).timestamp()))]),
                            steam_page([]), FakeResponse(404)]
    response = client.post("/games/620/updates/fetch")
    assert response.status_code == 502
    assert conn.execute("SELECT count(*) FROM update_review_days").fetchone()[0] == 2
    assert conn.execute("SELECT sentiment_label FROM reviews WHERE recommendation_id = 500").fetchone()[0] is not None


def test_fetch_replaces_posts_that_no_longer_count(client, conn, fake_steam, fixed_today):
    add_review(conn, 1)
    add_update(conn, "gone", at(date(2026, 9, 10)), "An update that was deleted from Steam")
    mark_days_fetched(conn, window_days(date(2026, 9, 1)) + window_days(date(2026, 8, 1)))
    fake_steam.responses = [news_page(NEWS)]
    client.post("/games/620/updates/fetch")
    assert conn.execute("SELECT gid FROM game_updates ORDER BY gid").fetchall() == [("1",), ("2",)]


def test_fetch_when_steam_rate_limits_midway(client, conn, fake_steam, fixed_today):
    add_review(conn, 1)
    fake_steam.responses = [news_page(NEWS), steam_page([]), steam_page([])] + [FakeResponse(429)] * 3
    response = client.post("/games/620/updates/fetch")
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"
    assert "try again in a minute" in response.json()["detail"]
    assert conn.execute("SELECT count(*) FROM update_review_days").fetchone()[0] == 2  # kept for next time


def test_fetch_when_steam_news_fails(client, conn, fake_steam, fixed_today):
    add_review(conn, 1)
    fake_steam.responses = [FakeResponse(503)] * 3
    response = client.post("/games/620/updates/fetch")
    assert response.status_code == 502
    assert "Steam news error" in response.json()["detail"]


def test_fetch_when_the_news_has_no_updates(client, conn, fake_steam, fixed_today):
    add_review(conn, 1)
    fake_steam.responses = [news_page([news_item(3, "Summer Sale!", at(date(2026, 8, 20)))])]
    assert client.post("/games/620/updates/fetch").json() == {
        "app_id": 620, "updates_found": 0, "fetched_day": None, "new_reviews": 0, "remaining": 0}
