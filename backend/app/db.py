"""Saving, scoring and topic-tagging reviews in PostgreSQL. Shared by the API and the command-line scripts."""

import os

import psycopg
from dotenv import load_dotenv

from app.sentiment import score_many
from app.topics import tag_many

SCORE_BATCH_SIZE = 1000

INSERT_SQL = """
    INSERT INTO reviews (
        recommendation_id, app_id, review_text, voted_up,
        playtime_at_review_minutes, helpful_votes, created_at
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (recommendation_id) DO NOTHING
"""

# Walk the table in recommendation_id order, one batch at a time, so memory use
# stays flat no matter how many reviews there are.
SELECT_TO_SCORE_SQL = """
    SELECT recommendation_id, review_text
    FROM reviews
    WHERE recommendation_id > %(after)s
      AND (%(app_id)s::int IS NULL OR app_id = %(app_id)s)  -- one game, or every game
      AND (%(rescore)s OR sentiment_label IS NULL)           -- with rescore, include already-scored reviews
    ORDER BY recommendation_id
    LIMIT %(limit)s
"""

UPDATE_SQL = """
    UPDATE reviews
    SET sentiment_compound = %s, sentiment_label = %s
    WHERE recommendation_id = %s
"""

# Rescoring replaces a review's topic tags, so remove the old ones first.
DELETE_TOPICS_SQL = "DELETE FROM review_topics WHERE recommendation_id = ANY(%s)"

INSERT_TOPIC_SQL = """
    INSERT INTO review_topics (recommendation_id, topic, excerpt, sentiment_score, sentiment_label)
    VALUES (%s, %s, %s, %s, %s)
"""


def database_url() -> str:
    """DATABASE_URL from the environment, or from the .env file in the project root."""
    load_dotenv()
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env first.")
    return url


def save_reviews(conn: psycopg.Connection, rows: list[tuple]) -> int:
    """Insert rows, skipping reviews already in the table. Returns how many were new."""
    with conn.cursor() as cur:
        cur.executemany(INSERT_SQL, rows)
        new_rows = cur.rowcount
    conn.commit()  # commit each page so progress is kept if fetching stops midway
    return new_rows


def score_reviews(conn: psycopg.Connection, app_id: int | None = None, rescore: bool = False) -> int:
    """
    Give every unscored review (for one game, or all games) a sentiment score and label, and
    tag the topics it mentions. With rescore=True, redo reviews that were already scored.
    Returns how many were scored.
    """
    last_id = 0
    total = 0
    while True:
        with conn.cursor() as cur:
            cur.execute(SELECT_TO_SCORE_SQL, {
                "after": last_id, "app_id": app_id, "rescore": rescore, "limit": SCORE_BATCH_SIZE,
            })
            batch = cur.fetchall()
            if not batch:
                return total
            ids = [review_id for review_id, _ in batch]
            texts = [text for _, text in batch]
            scored = score_many(texts)  # one batch call is much faster than one per review
            cur.executemany(UPDATE_SQL, [(s, label, review_id) for (s, label), review_id in zip(scored, ids)])
            cur.execute(DELETE_TOPICS_SQL, (ids,))
            cur.executemany(INSERT_TOPIC_SQL, [
                (review_id, topic, excerpt, s, label)
                for review_id, topics in zip(ids, tag_many(texts))
                for topic, (excerpt, s, label) in topics.items()
            ])
        conn.commit()  # commit each batch so progress is kept if scoring stops midway
        last_id = batch[-1][0]
        total += len(batch)
