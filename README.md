# Steam Review Sentiment Dashboard

A data pipeline and dashboard for analyzing player sentiment in Steam game reviews.

**Tech:** Python · PostgreSQL · VADER · Docker Compose · FastAPI and React (in development)

## Features

- Fetches English reviews for any Steam game from Steam's public reviews API, following cursor-based pagination
- Stores reviews in PostgreSQL with idempotent inserts, so re-running never creates duplicates
- Retries failed requests with exponential backoff and commits page by page, so progress survives interruptions
- Scores each review's sentiment with VADER, after removing Steam's BBCode tags and ♥ profanity censoring
- Measures how often the sentiment label agrees with the reviewer's own Recommended / Not recommended vote, compared against a majority-class baseline

## Project structure

```
steam-review-sentiment/
├── docker-compose.yml             # Runs PostgreSQL
├── .env.example                   # Template for database credentials
├── db/
│   └── init.sql                   # Creates the reviews table (safe to re-run)
└── backend/
    ├── requirements.txt           # Python dependencies
    └── scripts/
        ├── fetch_reviews.py       # Steam API -> PostgreSQL
        ├── score_sentiment.py     # VADER score + label for each review
        └── evaluate_sentiment.py  # Agreement between VADER and Steam's voted_up
```

## Getting started

**Prerequisites:** Docker Desktop and Python 3.10+ (the `python3` built into macOS is 3.9; install a newer one with `brew install python@3.13`)

1. Create your `.env` file (then change the password in both places it appears):
   ```bash
   cp .env.example .env
   ```

2. Start the database:
   ```bash
   docker compose up -d
   ```

3. Install the Python dependencies (a virtual environment is recommended):
   ```bash
   python -m venv .venv          # macOS: python3.13 -m venv .venv
   .venv\Scripts\activate        # Windows  (macOS/Linux: source .venv/bin/activate)
   pip install -r backend/requirements.txt
   ```

4. Fetch reviews for a game. The app ID is the number in its store URL, e.g. `store.steampowered.com/app/620/Portal_2`:
   ```bash
   python backend/scripts/fetch_reviews.py 620
   python backend/scripts/fetch_reviews.py 620 --max-reviews 5000
   ```

5. Score sentiment. Only reviews without a score are processed, so run it again after each fetch (`--rescore` recomputes everything):
   ```bash
   python backend/scripts/score_sentiment.py
   ```

6. Measure how well the sentiment labels match the reviewers' own votes, for all games or one:
   ```bash
   python backend/scripts/evaluate_sentiment.py
   python backend/scripts/evaluate_sentiment.py 620
   ```
   Read the agreement next to the baseline it prints. Most Steam reviews are Recommended, so always guessing "Recommended" already scores high.

7. Look at the data:
   ```bash
   docker compose exec db psql -U steam -d steam_reviews -c "SELECT app_id, sentiment_label, count(*) FROM reviews GROUP BY 1, 2 ORDER BY 1, 2;"
   ```

## Running without Docker

The script only needs a `DATABASE_URL`, so a PostgreSQL install directly on Windows/macOS works too:

1. Install PostgreSQL from postgresql.org/download (macOS: `brew install postgresql@18`, then `brew services start postgresql@18`).
2. In `psql`, create the database and table:
   ```sql
   CREATE DATABASE steam_reviews;
   \c steam_reviews
   \i db/init.sql
   ```
3. In `.env`, point `DATABASE_URL` at it:
   ```
   DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/steam_reviews
   ```
4. Continue from step 3 of Getting started above.

## Notes

- `db/init.sql` only runs automatically when the database volume is **empty**. It is safe to re-run, so to add new columns to an existing database without losing data, run it yourself: `docker compose exec db psql -U steam -d steam_reviews -f /docker-entrypoint-initdb.d/init.sql` (without Docker: `psql "$DATABASE_URL" -f db/init.sql`).
- Running the script again for the same game is safe: reviews that are already saved are skipped.
- If port 5432 is already in use (for example, by a local PostgreSQL install), change the left side of `"5432:5432"` in `docker-compose.yml` and the port in `DATABASE_URL`.
