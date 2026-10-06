-- Runs automatically the first time the Postgres container starts with an empty volume.

CREATE TABLE IF NOT EXISTS reviews (
    recommendation_id          BIGINT PRIMARY KEY,         -- Steam's unique ID for the review
    app_id                     INTEGER NOT NULL,           -- which game the review is for
    review_text                TEXT NOT NULL,
    voted_up                   BOOLEAN NOT NULL,           -- true = "Recommended"
    playtime_at_review_minutes INTEGER,                    -- minutes played when the review was written
    helpful_votes              INTEGER NOT NULL DEFAULT 0, -- how many people marked it helpful
    created_at                 TIMESTAMPTZ NOT NULL,       -- when the review was posted
    fetched_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The dashboard will almost always filter by game, so index that column.
CREATE INDEX IF NOT EXISTS idx_reviews_app_id ON reviews (app_id);

-- Sentiment, filled in by backend/scripts/score_sentiment.py (NULL until a review is scored).
-- Added with ALTER TABLE ... IF NOT EXISTS so this file can be re-run on an existing
-- database to pick up new columns without deleting any data.
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS sentiment_compound REAL;  -- VADER score, -1 (most negative) to +1 (most positive)
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS sentiment_label TEXT
    CHECK (sentiment_label IN ('positive', 'neutral', 'negative'));
