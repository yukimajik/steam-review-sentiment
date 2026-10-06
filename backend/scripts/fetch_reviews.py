"""
Fetch English reviews for one Steam game and save them to PostgreSQL.
Score them afterwards with score_sentiment.py (the API's POST /games/{app_id}/fetch does both).

Usage (from the project root, with the database running):
    python backend/scripts/fetch_reviews.py 620
    python backend/scripts/fetch_reviews.py 620 --max-reviews 5000
"""

import argparse
import logging
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # lets the script import the app package
from app import db  # noqa: E402
from app.steam import SteamError, fetch_reviews, to_row  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch English Steam reviews into PostgreSQL.")
    parser.add_argument("app_id", type=int, help="Steam app ID (the number in the store URL), e.g. 620")
    parser.add_argument("--max-reviews", type=int, default=1000,
                        help="stop after this many reviews (default: 1000)")
    args = parser.parse_args()
    logging.basicConfig(format="  %(message)s")  # shows the "retrying in Ns" warnings

    total_fetched = 0
    total_new = 0
    with psycopg.connect(db.database_url()) as conn:
        try:
            for page in fetch_reviews(args.app_id, args.max_reviews):
                rows = [to_row(args.app_id, review) for review in page]
                total_new += db.save_reviews(conn, rows)
                total_fetched += len(rows)
                print(f"Fetched {total_fetched} reviews ({total_new} new)")
        except SteamError as error:
            raise SystemExit(f"Stopped: {error}. The {total_new} new reviews fetched before this are saved.")

    if total_fetched == 0:
        # Steam answers success=1 with no reviews even for app IDs that don't exist
        print(f"No English reviews found for app {args.app_id}. Double-check the app ID.")
    else:
        print(f"Done. Saved {total_new} new reviews for app {args.app_id}.")


if __name__ == "__main__":
    main()
