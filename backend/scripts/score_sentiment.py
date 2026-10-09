"""
Score each review's text with the sentiment classifier, tag the topics it mentions
(backend/app/topics.py), and save the results to PostgreSQL.

Only reviews without a score are processed, so run this again after fetching more
reviews. Use --rescore to redo every review, e.g. after retraining the model with
backend/scripts/train_model.py or changing the topic keywords.

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
    parser = argparse.ArgumentParser(description="Score Steam reviews with the sentiment classifier and tag their topics.")
    parser.add_argument("--rescore", action="store_true",
                        help="also redo reviews that were already scored")
    args = parser.parse_args()

    with psycopg.connect(db.database_url()) as conn:
        scored = db.score_reviews(conn, rescore=args.rescore)

    if scored == 0:
        print("No unscored reviews found. Fetch more with fetch_reviews.py, "
              "or use --rescore to recompute existing scores.")
    else:
        print(f"Done. Scored and topic-tagged {scored} reviews.")


if __name__ == "__main__":
    main()
