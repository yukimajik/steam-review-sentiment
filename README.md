# Steam Review Sentiment Dashboard

A data pipeline and dashboard for analyzing player sentiment in Steam game reviews.

**Tech:** Python · FastAPI · PostgreSQL · VADER · Docker Compose · pytest · React · TypeScript · Vite · Recharts

## Features

- Fetches English reviews for any Steam game from Steam's public reviews API, following cursor-based pagination
- Stores reviews in PostgreSQL with idempotent inserts, so re-running never creates duplicates
- Retries network errors, rate limits (honoring `Retry-After`) and Steam server errors with exponential backoff, and commits page by page so progress survives interruptions
- Scores each review's sentiment with VADER, after removing Steam's BBCode tags and ♥ profanity censoring
- Measures how often the sentiment label agrees with the reviewer's own Recommended / Not recommended vote, compared against a majority-class baseline
- REST API with endpoints for fetching, a summary, a monthly trend, and filtered, paginated reviews; CORS enabled for a local React frontend
- pytest suite that runs against a separate test database, with Steam faked so tests never touch the network
- React dashboard: search by app ID, summary cards, sentiment pie chart, monthly trend line, and a filterable, paginated review list, with loading and error states and a layout that works on phones

## Project structure

```
steam-review-sentiment/
├── docker-compose.yml             # Runs PostgreSQL and the API
├── .env.example                   # Template for database credentials and settings
├── pytest.ini                     # Test settings
├── db/
│   └── init.sql                   # Creates the reviews table (safe to re-run)
├── docs/
│   └── HOW_IT_WORKS.md            # How everything works and why (learning doc)
├── frontend/                      # React dashboard (Vite + TypeScript)
│   ├── src/App.tsx                # The page: search, states, layout
│   ├── src/api.ts                 # API client and response types
│   ├── src/components/            # Search, summary cards, charts, review list
│   └── src/index.css              # Styles and responsive layout
└── backend/
    ├── Dockerfile                 # Builds the API image
    ├── requirements.txt           # Python dependencies
    ├── requirements-dev.txt       # + test dependencies
    ├── app/
    │   ├── main.py                # FastAPI app: endpoints, CORS, error handling
    │   ├── steam.py               # Steam API client (pagination, retries)
    │   ├── sentiment.py           # VADER scoring and labels
    │   └── db.py                  # Saving and scoring reviews in PostgreSQL
    ├── scripts/
    │   ├── fetch_reviews.py       # Steam API -> PostgreSQL (command line)
    │   ├── score_sentiment.py     # VADER score + label for each review
    │   └── evaluate_sentiment.py  # Agreement between VADER and Steam's voted_up
    └── tests/                     # pytest tests
```

## Getting started

**Prerequisites:** Docker Desktop (or another Docker engine such as OrbStack)

1. Create your `.env` file (then change the password in both places it appears):
   ```bash
   cp .env.example .env
   ```

2. Start the database and the API:
   ```bash
   docker compose up -d --build
   ```

3. Fetch and score reviews for a game. The app ID is the number in its store URL, e.g. `store.steampowered.com/app/620/Portal_2`. The request waits until it's done (about 25–30 seconds for 2,000 reviews):
   ```bash
   curl -X POST "http://localhost:8000/games/620/fetch?max_reviews=2000"
   ```

4. Explore the API in your browser at http://localhost:8000/docs, or with curl:
   ```bash
   curl http://localhost:8000/games/620/summary
   ```

## Dashboard

Needs Node.js 20.19+ or 22.12+ and the API running (step 2 above).

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 and search for an app ID. If the game isn't stored yet, the page offers to fetch its 1,000 newest reviews from Steam (about 10–15 seconds).

The dashboard calls the API at `http://localhost:8000` by default. To use another address, copy `frontend/.env.example` to `frontend/.env` and change `VITE_API_URL`. If the dashboard runs on an address other than `http://localhost:5173`, add it to `CORS_ORIGINS` in the main `.env`.

Other commands, run inside `frontend/`: `npm run build` type-checks and builds for production, and `npm run lint` checks the code.

## API

| Endpoint | What it returns |
|---|---|
| `POST /games/{app_id}/fetch?max_reviews=1000` | Fetches the newest English reviews (1–5,000), saves new ones, scores them. Returns `fetched`, `new`, `scored`. |
| `GET /games/{app_id}/summary` | Total reviews, % positive / neutral / negative, `agreement_pct` (VADER label matches the player's vote; neutral counts as a miss), and `baseline_pct` (what always guessing the more common vote would score). |
| `GET /games/{app_id}/trend` | Average VADER score and review count per month (UTC), by the date reviews were posted. |
| `GET /games/{app_id}/reviews?sentiment=negative&page=1&page_size=20` | Reviews newest first, optionally one sentiment. `page_size` up to 100; `total` is the count across all pages. |

Errors: `404` when a game has no stored reviews (fetch it first) or Steam has none, `422` for invalid input, `502` when Steam fails after retries, `503` when the database is unreachable.

Each fetch starts from the newest review, so fetching again only adds reviews posted since. To reach further back in time (a longer trend), use a bigger `max_reviews`.

## Command-line scripts and tests

These run on your machine, so they need Python 3.10+ (the `python3` built into macOS is 3.9; install a newer one with `brew install python@3.13`).

1. Create a virtual environment and install the dependencies:
   ```bash
   python -m venv .venv          # macOS: python3.13 -m venv .venv
   .venv\Scripts\activate        # Windows  (macOS/Linux: source .venv/bin/activate)
   pip install -r backend/requirements-dev.txt
   ```

2. Run the tests (the database must be running; tests create and use a separate `steam_reviews_test` database):
   ```bash
   pytest
   ```

3. The scripts do the same jobs as the API, from the command line:
   ```bash
   python backend/scripts/fetch_reviews.py 620 --max-reviews 5000   # fetch only
   python backend/scripts/score_sentiment.py                        # score unscored reviews (--rescore: all)
   python backend/scripts/evaluate_sentiment.py 620                 # detailed agreement table
   ```
   They also work inside the API container, e.g. `docker compose exec api python scripts/evaluate_sentiment.py 620`.

## Running without Docker

The code only needs a `DATABASE_URL`, so a PostgreSQL install directly on Windows/macOS works too:

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
4. Set up Python as in step 1 of the section above, then start the API:
   ```bash
   uvicorn --app-dir backend app.main:app --reload
   ```

## Notes

- `db/init.sql` only runs automatically when the database volume is **empty**. It is safe to re-run, so to add new columns to an existing database without losing data, run it yourself: `docker compose exec db psql -U steam -d steam_reviews -f /docker-entrypoint-initdb.d/init.sql` (without Docker: `psql "$DATABASE_URL" -f db/init.sql`).
- If port 5432 is already in use (for example, by a local PostgreSQL install), change the left side of `"5432:5432"` in `docker-compose.yml` and the port in `DATABASE_URL`.
- To let a frontend on a different address call the API, set `CORS_ORIGINS` in `.env` (comma-separated) and run `docker compose up -d` again.
