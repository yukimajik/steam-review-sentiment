"""
Score each review's text with VADER and save the result to PostgreSQL.

Only reviews without a score are processed, so run this again after fetching more
reviews. Use --rescore to recompute every review (e.g. after changing the thresholds
in backend/app/sentiment.py).

Usage (from the project root, with the database running):
    python backend/scripts/score_sentiment.py
    python backend/scripts/score_sentiment.py --rescore
"""

import argparse
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # lets the script import the app package
from app import db  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Score Steam reviews with VADER sentiment.")
    parser.add_argument("--rescore", action="store_true",
                        help="also recompute reviews that already have a score")
    args = parser.parse_args()

    with psycopg.connect(db.database_url()) as conn:
        scored = db.score_reviews(conn, rescore=args.rescore)

    if scored == 0:
        print("No unscored reviews found. Fetch more with fetch_reviews.py, "
              "or use --rescore to recompute existing scores.")
    else:
        print(f"Done. Scored {scored} reviews.")


if __name__ == "__main__":
    main()
