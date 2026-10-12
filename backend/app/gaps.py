"""
Filling the gaps in the weekly chart.

Older reviews are only fetched around updates (updates.py), so the weeks between updates have
none stored and the weekly chart has gaps. Filling a gap asks Steam for the newest 100 reviews
of that week: one request per week. That's a sample, not the whole week. A busy game gets
around 100 English reviews a day, so its sample comes from the last day or so of the week.
"""

import time
from datetime import date, datetime, time as day_time, timedelta, timezone

import psycopg

from app import db, steam

WEEKS_PER_REQUEST = 10  # one Steam request each, so a call takes about 12 seconds and the page can show progress

# Mondays (UTC) between the first and last week with stored reviews that have none, and haven't been
# filled yet (a filled week Steam had no reviews for stays empty). Same weeks and filter as the chart.
EMPTY_WEEKS_SQL = """
    WITH stored AS (
        SELECT DISTINCT date_trunc('week', created_at AT TIME ZONE 'UTC')::date AS week
        FROM reviews
        WHERE app_id = %(app_id)s AND sentiment_label IS NOT NULL
    )
    SELECT week::date
    FROM generate_series((SELECT min(week) FROM stored)::timestamp, (SELECT max(week) FROM stored)::timestamp,
                         interval '1 week') AS week
    WHERE week::date NOT IN (SELECT week FROM stored)
      AND week::date NOT IN (SELECT week FROM gap_weeks WHERE app_id = %(app_id)s)
    ORDER BY week DESC
"""
MARK_WEEK_SQL = "INSERT INTO gap_weeks (app_id, week) VALUES (%s, %s) ON CONFLICT DO NOTHING"


def empty_weeks(conn: psycopg.Connection, app_id: int) -> list[date]:
    """The Mondays of the weeks still to fill, newest first."""
    return [row[0] for row in conn.execute(EMPTY_WEEKS_SQL, {"app_id": app_id})]


def fill_weeks(conn: psycopg.Connection, app_id: int, weeks: list[date]) -> int:
    """Fetch the newest 100 reviews of each week, save them, and remember the week as done, so an
    interrupted fill picks up where it stopped. Returns how many reviews were new."""
    new = 0
    for i, monday in enumerate(weeks):
        if i:
            time.sleep(steam.DELAY_BETWEEN_PAGES)  # be polite to Steam
        start = datetime.combine(monday, day_time(), tzinfo=timezone.utc)
        reviews = steam.fetch_reviews_between(app_id, start, start + timedelta(weeks=1),
                                              f"app {app_id} in the week of {monday}")
        new += db.save_reviews(conn, [steam.to_row(app_id, r) for r in reviews])
        conn.execute(MARK_WEEK_SQL, (app_id, monday))
        conn.commit()
    return new
