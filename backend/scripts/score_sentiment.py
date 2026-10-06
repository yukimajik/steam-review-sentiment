"""
Score each review's text with VADER and save the result to PostgreSQL.

Only reviews without a score are processed, so run this again after fetching more
reviews. Use --rescore to recompute every review (e.g. after changing the thresholds).

Usage (from the project root, with the database running):
    python backend/scripts/score_sentiment.py
    python backend/scripts/score_sentiment.py --rescore
"""

import argparse
import os
import re

import psycopg
from dotenv import load_dotenv
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

BATCH_SIZE = 1000

# VADER's recommended cutoffs for turning the compound score into a label.
POSITIVE_THRESHOLD = 0.05
NEGATIVE_THRESHOLD = -0.05

# Steam's formatting tags, e.g. [b]...[/b], [url=...], [*]. VADER reads "[b]great[/b]"
# as one unknown word and scores it 0, so the tags are removed before scoring.
BBCODE_TAG = re.compile(
    r"\[/?(?:h[1-3]|b|u|i|strike|spoiler|noparse|hr|url|quote|code|list|olist|table|tr|th|td|\*)"
    r"(?:=[^\]]*)?\]",
    re.IGNORECASE,
)

# Steam hides profanity as hearts ("this game is ♥♥♥♥"). VADER reads ♥ as a strongly
# positive emoji, which makes angry reviews look glowing, so the hearts are removed too.
CENSORED_WORD = re.compile("♥+")

# Walk the table in recommendation_id order, one batch at a time, so memory use
# stays flat no matter how many reviews there are.
SELECT_SQL = """
    SELECT recommendation_id, review_text
    FROM reviews
    WHERE recommendation_id > %s
      AND (%s OR sentiment_label IS NULL)  -- with --rescore, include already-scored reviews
    ORDER BY recommendation_id
    LIMIT %s
"""

UPDATE_SQL = """
    UPDATE reviews
    SET sentiment_compound = %s, sentiment_label = %s
    WHERE recommendation_id = %s
"""


def label_for(compound: float) -> str:
    """Turn VADER's compound score (-1 to +1) into positive, neutral, or negative."""
    if compound >= POSITIVE_THRESHOLD:
        return "positive"
    if compound <= NEGATIVE_THRESHOLD:
        return "negative"
    return "neutral"


def score(analyzer: SentimentIntensityAnalyzer, text: str) -> tuple[float, str]:
    """Return (compound score, label) for one review's text."""
    # Replace with a space, so "a[hr]b" doesn't become "ab"
    cleaned = CENSORED_WORD.sub(" ", BBCODE_TAG.sub(" ", text))
    compound = analyzer.polarity_scores(cleaned)["compound"]
    return compound, label_for(compound)


def main() -> None:
    parser = argparse.ArgumentParser(description="Score Steam reviews with VADER sentiment.")
    parser.add_argument("--rescore", action="store_true",
                        help="also recompute reviews that already have a score")
    args = parser.parse_args()

    load_dotenv()  # finds the .env file in the project root
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is not set. Copy .env.example to .env first.")

    analyzer = SentimentIntensityAnalyzer()  # loads VADER's word list once
    last_id = 0
    total = 0
    with psycopg.connect(database_url) as conn:
        while True:
            with conn.cursor() as cur:
                cur.execute(SELECT_SQL, (last_id, args.rescore, BATCH_SIZE))
                batch = cur.fetchall()
                if not batch:
                    break
                updates = [(*score(analyzer, text), review_id) for review_id, text in batch]
                cur.executemany(UPDATE_SQL, updates)
            conn.commit()  # commit each batch so progress is kept if the script stops midway
            last_id = batch[-1][0]
            total += len(batch)
            print(f"Scored {total} reviews")

    if total == 0:
        print("No unscored reviews found. Fetch more with fetch_reviews.py, "
              "or use --rescore to recompute existing scores.")
    else:
        print(f"Done. Scored {total} reviews.")


if __name__ == "__main__":
    main()
