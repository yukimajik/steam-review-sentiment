"""
Game updates, found in each game's official Steam news, and how review sentiment compares
in the 2 weeks before and the 2 weeks after each one.

This only compares before and after. Sales, events, a new season and new players arrive
around the same time as updates, so a shift doesn't show that the update caused it.
"""

import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as day_time, timedelta, timezone

import psycopg
from psycopg.rows import dict_row

from app import db, steam

WINDOW_DAYS = 14     # compare the 14 days before an update with the 14 days after it
LOOKBACK_DAYS = 365  # only updates from the last 12 months
MAX_UPDATES = 10     # most recent updates analyzed per game: each one costs 28 requests to Steam
MIN_REVIEWS = 30     # reviews needed on each side to be listed among the biggest shifts
TOP_SHIFTS = 3

# Which official posts count as an update, checked against the real posts of every stored game.
# Steam's own "patchnotes" tag is reliable but many developers never use it, so titles count too.
UPDATE_TITLE = re.compile(
    r"\b(?:patch|hot ?fix|changelog|release notes?)"
    r"|\d+\.\d+(?:\.\d+)+"                          # version numbers like 1.16.244 or 10.2.0
    r"|\bv(?:er(?:sion)?)?\.? ?\d+(?:\.\d+)+",      # Ver.1.042, Version 1.17, v2.1
    re.IGNORECASE,
)
# "update" alone is mostly dev blogs ("Blog Update #50", "Community Update #36"), so it only
# counts when the title says it's out ("The Peer-to-Peer update is now live!").
LIVE_TITLE = re.compile(r"\b(?:update|season)\b.*\b(?:now live|out now|is live)\b", re.IGNORECASE)
# Posts about an update that isn't live yet, or about a test server.
NOT_LIVE_TITLE = re.compile(
    r"\bPTB\b|preview|test build|announcement|notice|coming|introducing|sneak peek|\bdev(?:eloper)? update",
    re.IGNORECASE,
)


def is_update(post: dict) -> bool:
    """Does this official news post announce a released update?"""
    if "patchnotes" in post["tags"]:
        return True
    title = post["title"]
    return bool(UPDATE_TITLE.search(title) or LIVE_TITLE.search(title)) and not NOT_LIVE_TITLE.search(title)


@dataclass
class UpdateGroup:
    """One update, plus any further update posts less than WINDOW_DAYS after it."""
    day: date  # the first post's day (UTC)
    posts: list[dict] = field(default_factory=list)


def group_updates(posts: list[dict]) -> list[UpdateGroup]:
    """Oldest first. A post less than WINDOW_DAYS after a group's first post joins that group:
    otherwise a hotfix's "before" window would be mostly the main update's "after" window."""
    groups: list[UpdateGroup] = []
    for post in sorted(posts, key=lambda p: p["posted_at"]):
        day = post["posted_at"].astimezone(timezone.utc).date()
        if groups and day < groups[-1].day + timedelta(days=WINDOW_DAYS):
            groups[-1].posts.append(post)
        else:
            groups.append(UpdateGroup(day, [post]))
    return groups


def window_days(day: date) -> list[date]:
    """The 14 days before and the 14 days after an update. The update's own day is left out,
    because it mixes reviews written before and after the update."""
    return ([day - timedelta(days=n) for n in range(WINDOW_DAYS, 0, -1)]
            + [day + timedelta(days=n) for n in range(1, WINDOW_DAYS + 1)])


def after_window_ended(day: date, today: date) -> bool:
    return day + timedelta(days=WINDOW_DAYS) < today  # the last "after" day is over


def midnight(day: date) -> datetime:
    return datetime.combine(day, day_time(), tzinfo=timezone.utc)


# ---------- the database ----------

DELETE_POSTS_SQL = "DELETE FROM game_updates WHERE app_id = %s"
INSERT_POST_SQL = """
    INSERT INTO game_updates (gid, app_id, title, url, posted_at) VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT (gid) DO NOTHING
"""
SELECT_POSTS_SQL = """
    SELECT gid, title, url, posted_at FROM game_updates
    WHERE app_id = %s AND posted_at >= %s
"""
FETCHED_DAYS_SQL = "SELECT day FROM update_review_days WHERE app_id = %s AND day = ANY(%s)"
MARK_DAY_SQL = "INSERT INTO update_review_days (app_id, day) VALUES (%s, %s) ON CONFLICT DO NOTHING"

# Reviews in [start, end): how many, their average score, and how many players recommended the game
WINDOW_STATS_SQL = """
    SELECT count(*), avg(sentiment_compound), count(*) FILTER (WHERE voted_up)
    FROM reviews
    WHERE app_id = %s AND sentiment_label IS NOT NULL AND created_at >= %s AND created_at < %s
"""


def save_posts(conn: psycopg.Connection, app_id: int, posts: list[dict]) -> None:
    """Replace the game's stored update posts with these, so a post that no longer counts is dropped."""
    with conn.cursor() as cur:
        cur.execute(DELETE_POSTS_SQL, (app_id,))
        cur.executemany(INSERT_POST_SQL, [(p["gid"], app_id, p["title"], p["url"], p["posted_at"]) for p in posts])
    conn.commit()


def in_lookback(posts: list[dict], today: date) -> list[dict]:
    """The posts from the last 12 months."""
    since = midnight(today - timedelta(days=LOOKBACK_DAYS))
    return [p for p in posts if p["posted_at"] >= since]


def stored_groups(conn: psycopg.Connection, app_id: int, today: date) -> list[UpdateGroup]:
    """Update groups from the last 12 months, oldest first."""
    since = midnight(today - timedelta(days=LOOKBACK_DAYS))
    with conn.cursor(row_factory=dict_row) as cur:
        posts = cur.execute(SELECT_POSTS_SQL, (app_id, since)).fetchall()
    return group_updates(posts)


def missing_days(conn: psycopg.Connection, app_id: int, day: date) -> list[date]:
    """The days around the update on `day` whose reviews haven't been fetched yet."""
    days = window_days(day)
    fetched = {row[0] for row in conn.execute(FETCHED_DAYS_SQL, (app_id, days))}
    return [d for d in days if d not in fetched]


def window_stats(conn: psycopg.Connection, app_id: int, first: date, last: date) -> dict:
    """Reviews posted from the start of `first` to the end of `last`."""
    reviews, avg, recommended = conn.execute(
        WINDOW_STATS_SQL, (app_id, midnight(first), midnight(last + timedelta(days=1)))
    ).fetchone()
    return {
        "reviews": reviews,
        "avg_score": None if avg is None else round(avg, 3),
        "recommended_pct": None if reviews == 0 else round(100 * recommended / reviews, 1),
    }


def compare(conn: psycopg.Connection, app_id: int, today: date) -> list[dict]:
    """Every update group from the last 12 months, newest first, with its status and, once its
    reviews are fetched, the before and after numbers. Statuses:
      too_recent       the 2 weeks after it aren't over yet
      needs_reviews    the reviews around it haven't been fetched yet
      too_few_reviews  fewer than MIN_REVIEWS on one side, so it isn't ranked
      ready            can be ranked among the biggest shifts
    Only the MAX_UPDATES most recent finished updates are listed, since each costs 28 requests to fetch."""
    groups = stored_groups(conn, app_id, today)
    finished = [g for g in groups if after_window_ended(g.day, today)][-MAX_UPDATES:]
    open_ = [g for g in groups if not after_window_ended(g.day, today)]

    results = []
    for group in reversed(finished + open_):  # newest first
        result = {"day": group.day, "posts": group.posts, "status": "too_recent",
                  "before": None, "after": None, "shift": None}
        if after_window_ended(group.day, today):
            if missing_days(conn, app_id, group.day):
                result["status"] = "needs_reviews"
            else:
                before = window_stats(conn, app_id, group.day - timedelta(days=WINDOW_DAYS), group.day - timedelta(days=1))
                after = window_stats(conn, app_id, group.day + timedelta(days=1), group.day + timedelta(days=WINDOW_DAYS))
                enough = before["reviews"] >= MIN_REVIEWS and after["reviews"] >= MIN_REVIEWS
                result.update(
                    status="ready" if enough else "too_few_reviews",
                    before=before,
                    after=after,
                    shift=None if before["avg_score"] is None or after["avg_score"] is None
                    else round(after["avg_score"] - before["avg_score"], 3),
                )
        results.append(result)
    return results


def biggest_shifts(results: list[dict]) -> tuple[list[dict], list[dict]]:
    """The TOP_SHIFTS biggest rises and drops in average score, among ranked ("ready") updates."""
    ready = [r for r in results if r["status"] == "ready"]
    rises = sorted((r for r in ready if r["shift"] > 0), key=lambda r: r["shift"], reverse=True)
    drops = sorted((r for r in ready if r["shift"] < 0), key=lambda r: r["shift"])
    return rises[:TOP_SHIFTS], drops[:TOP_SHIFTS]


def fetch_window_reviews(conn: psycopg.Connection, app_id: int, days: list[date]) -> int:
    """Fetch up to 100 reviews for each day, save them, and remember the day as done, so an
    interrupted fetch picks up where it stopped. Returns how many reviews were new."""
    new = 0
    for i, day in enumerate(days):
        if i:
            time.sleep(steam.DELAY_BETWEEN_PAGES)  # be polite to Steam
        reviews = steam.fetch_reviews_on_day(app_id, day)
        new += db.save_reviews(conn, [steam.to_row(app_id, r) for r in reviews])
        conn.execute(MARK_DAY_SQL, (app_id, day))
        conn.commit()
    return new


def today() -> date:
    return datetime.now(timezone.utc).date()
