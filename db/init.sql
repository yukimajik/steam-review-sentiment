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
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS sentiment_compound REAL;  -- model score, -1 (likely Not recommended) to +1 (likely Recommended)
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS sentiment_label TEXT
    CHECK (sentiment_label IN ('positive', 'neutral', 'negative'));

-- Topics each review mentions (performance, bugs, ...), filled in alongside the sentiment by
-- backend/app/topics.py. One row per review per topic. The excerpt is the part of the review
-- that mentions the topic, and its sentiment is the classifier's verdict on that part alone.
CREATE TABLE IF NOT EXISTS review_topics (
    recommendation_id BIGINT NOT NULL REFERENCES reviews ON DELETE CASCADE,
    topic             TEXT NOT NULL,  -- e.g. 'performance'; the list of topics lives in topics.py
    excerpt           TEXT NOT NULL,
    sentiment_score   REAL NOT NULL,  -- -1 (likely a complaint) to +1 (likely praise)
    sentiment_label   TEXT NOT NULL CHECK (sentiment_label IN ('positive', 'neutral', 'negative')),
    PRIMARY KEY (recommendation_id, topic)
);
