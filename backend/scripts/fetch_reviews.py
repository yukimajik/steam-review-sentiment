"""
Fetch English reviews for one Steam game and save them to PostgreSQL.

Usage (from the project root, with the database running):
    python backend/scripts/fetch_reviews.py 620
    python backend/scripts/fetch_reviews.py 620 --max-reviews 5000
"""

import argparse
import os
import time
from datetime import datetime, timezone

import psycopg
import requests
from dotenv import load_dotenv

STEAM_REVIEWS_URL = "https://store.steampowered.com/appreviews/{app_id}"
PAGE_SIZE = 100            # Steam's maximum reviews per request
DELAY_BETWEEN_PAGES = 1.0  # seconds; be polite to Steam's servers
MAX_RETRIES = 3

INSERT_SQL = """
    INSERT INTO reviews (
        recommendation_id, app_id, review_text, voted_up,
        playtime_at_review_minutes, helpful_votes, created_at
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (recommendation_id) DO NOTHING
"""


def fetch_page(app_id: int, cursor: str) -> dict:
    """Request one page of reviews from Steam, retrying on network or server errors."""
    params = {
        "json": 1,
        "language": "english",
        "filter": "recent",       # newest first; gives stable cursor pagination
        "review_type": "all",     # positive and negative
        "purchase_type": "all",   # bought on Steam or elsewhere
        "num_per_page": PAGE_SIZE,
        "cursor": cursor,         # requests URL-encodes this (cursors contain + / =)
    }
    url = STEAM_REVIEWS_URL.format(app_id=app_id)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()  # turn 4xx/5xx responses into exceptions
            return response.json()
        except requests.RequestException as error:
            if attempt == MAX_RETRIES:
                raise
            wait = 2 ** attempt  # exponential backoff: 2s, then 4s
            print(f"  Request failed ({error}), retrying in {wait}s...")
            time.sleep(wait)


def fetch_reviews(app_id: int, max_reviews: int):
    """
    Yield reviews one page at a time, following Steam's cursor until there are
    no more reviews or we reach max_reviews.
    """
    cursor = "*"  # "*" means "start from the beginning"
    fetched = 0

    while fetched < max_reviews:
        data = fetch_page(app_id, cursor)
        if data.get("success") != 1:
            raise RuntimeError(f"Steam returned success={data.get('success')} for app {app_id}")

        reviews = data.get("reviews", [])
        if not reviews:
            break  # nothing left to fetch

        reviews = reviews[: max_reviews - fetched]  # don't go past the limit
        yield reviews
        fetched += len(reviews)

        next_cursor = data["cursor"]
        if next_cursor == cursor:
            break  # Steam repeats the cursor when there are no further pages
        cursor = next_cursor
        time.sleep(DELAY_BETWEEN_PAGES)


def to_row(app_id: int, review: dict) -> tuple:
    """Pick out the fields we store from one review in Steam's JSON."""
    return (
        int(review["recommendationid"]),              # Steam sends IDs as strings
        app_id,
        review["review"],
        review["voted_up"],
        review["author"].get("playtime_at_review"),   # minutes; not always present
        review.get("votes_up", 0),
        datetime.fromtimestamp(review["timestamp_created"], tz=timezone.utc),  # Unix seconds -> datetime
    )


def save_reviews(conn: psycopg.Connection, rows: list[tuple]) -> int:
    """Insert rows, skipping reviews already in the table. Returns how many were new."""
    with conn.cursor() as cur:
        cur.executemany(INSERT_SQL, rows)
        new_rows = cur.rowcount
    conn.commit()  # commit each page so progress is kept if the script stops midway
    return new_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch English Steam reviews into PostgreSQL.")
    parser.add_argument("app_id", type=int, help="Steam app ID (the number in the store URL), e.g. 620")
    parser.add_argument("--max-reviews", type=int, default=1000,
                        help="stop after this many reviews (default: 1000)")
    args = parser.parse_args()

    load_dotenv()  # finds the .env file in the project root
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is not set. Copy .env.example to .env first.")

    total_fetched = 0
    total_new = 0
    with psycopg.connect(database_url) as conn:
        for page in fetch_reviews(args.app_id, args.max_reviews):
            rows = [to_row(args.app_id, review) for review in page]
            total_new += save_reviews(conn, rows)
            total_fetched += len(rows)
            print(f"Fetched {total_fetched} reviews ({total_new} new)")

    if total_fetched == 0:
        # Steam answers success=1 with no reviews even for app IDs that don't exist
        print(f"No English reviews found for app {args.app_id}. Double-check the app ID.")
    else:
        print(f"Done. Saved {total_new} new reviews for app {args.app_id}.")


if __name__ == "__main__":
    main()
