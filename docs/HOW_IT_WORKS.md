# How It Works

A learning guide to this project: what each piece does, how data moves through it, why it was built this way, and how to talk about it in an interview. Every number here comes from a real run on this project's data (2,000 reviews each of Portal 2 and Cities: Skylines II, fetched October 2026).

**Built so far:** Phase 1 (fetch reviews into PostgreSQL), Phase 2 (VADER sentiment and measuring its accuracy), Phase 3 (FastAPI backend in Docker, with tests). The React frontend comes later.

---

## 1. What each file does

| File | What it does |
|---|---|
| `docker-compose.yml` | Starts two containers: `db` (PostgreSQL 17) and `api` (the FastAPI app). The API waits until the database is healthy. |
| `.env.example` | Template for `.env`, which holds the database password and settings. `.env` is git-ignored so secrets never get committed. |
| `db/init.sql` | Creates the `reviews` table and adds the sentiment columns. Runs automatically on a brand-new database and is safe to re-run on an existing one. |
| `backend/app/main.py` | The API: four endpoints, CORS, input validation, and turning errors into the right HTTP status codes. |
| `backend/app/steam.py` | Talks to Steam's reviews API: follows page cursors, retries failures, respects rate limits. |
| `backend/app/sentiment.py` | Cleans review text and scores it with VADER, then turns the score into positive / neutral / negative. |
| `backend/app/db.py` | Saves reviews (skipping duplicates) and scores unscored reviews in batches. Shared by the API and the scripts. |
| `backend/scripts/fetch_reviews.py` | Command-line version of fetching (without scoring). |
| `backend/scripts/score_sentiment.py` | Command-line scoring of unscored reviews; `--rescore` redoes all. |
| `backend/scripts/evaluate_sentiment.py` | Prints a detailed table of how VADER's labels compare to players' votes. |
| `backend/tests/` | 44 pytest tests: `test_api.py` (endpoints), `test_steam.py` (retries and errors), `test_sentiment.py` (scoring), plus shared setup in `conftest.py` and `helpers.py`. |
| `backend/Dockerfile` | Recipe for the API's container image. |
| `backend/requirements.txt` / `requirements-dev.txt` | Python packages for the app / extra ones for tests. |
| `pytest.ini` | Tells pytest where the code and tests live. |

### The `reviews` table

| Column | Meaning |
|---|---|
| `recommendation_id` | Steam's unique ID for the review (primary key, so duplicates are impossible) |
| `app_id` | Which game |
| `review_text` | What the player wrote |
| `voted_up` | The player's thumbs up (Recommended) or down (Not recommended) |
| `playtime_at_review_minutes`, `helpful_votes`, `created_at` | Extra details from Steam |
| `sentiment_compound` | VADER's score, from −1 (most negative) to +1 (most positive) |
| `sentiment_label` | `positive`, `neutral` or `negative`, derived from the score |

---

## 2. How data flows

### Fetching a game: `POST /games/620/fetch?max_reviews=2000`

1. **Validation.** FastAPI checks the app ID is a positive number that fits the database column, and `max_reviews` is 1–5,000. Anything else gets a `422` before any code runs.
2. **Connection.** `get_conn` opens a database connection for this request.
3. **First page.** `steam.fetch_page` asks Steam for 100 reviews with cursor `*` ("start from the newest").
4. **Save.** `steam.to_row` picks out the fields we store, and `db.save_reviews` inserts them with `ON CONFLICT DO NOTHING`, so reviews we already have are skipped. Each page is committed immediately.
5. **Next pages.** Steam's response includes a cursor pointing at the next page. We wait 1 second (to be polite) and ask again, until we hit `max_reviews`, get an empty page, or Steam repeats the cursor.
6. **If Steam fails.** Network errors, rate limits (`429`) and server errors (`5xx`) are retried up to 3 times. Anything else (like `404`) fails at once. If it still fails, the reviews already saved get scored and the API returns `502`.
7. **Nothing found.** If Steam had zero reviews (it answers "success" even for app IDs that don't exist), the API returns `404`.
8. **Scoring.** `db.score_reviews` reads this game's unscored reviews 1,000 at a time, and `sentiment.score` cleans each text and runs VADER. Scores and labels are written back, committing each batch.
9. **Response.** `{"fetched": 2000, "new": 2000, "scored": 2000}`. In real runs this took 26.4 and 27.7 seconds, almost all of it waiting on Steam. Scoring 4,000 reviews takes under a second.

### Reading: summary, trend, reviews

- **Summary** runs one SQL query that counts everything at once (`count(*) FILTER (WHERE ...)`): totals per label, Recommended votes, and agreements. Python turns the counts into percentages.
- **Trend** groups reviews by the month they were posted (in UTC) and averages the score.
- **Reviews** runs two queries: one counts matching reviews (for page numbers), one fetches the requested page, newest first.
- All three only look at **scored** reviews and return `404` if the game has none.

### The command-line scripts

They call the same `app` functions as the API, so there's one copy of the logic. `fetch_reviews.py` + `score_sentiment.py` together do what the fetch endpoint does.

### Docker

`docker compose up` starts the database, waits for its health check, then starts the API on port 8000. Inside Docker the API reaches the database at the hostname `db` (the service name). From your Mac, scripts and tests reach the same database at `localhost:5432` through the published port.

---

## 3. Design choices and alternatives

### Data and fetching

| Choice | Why | Alternatives |
|---|---|---|
| **PostgreSQL** | Real SQL with aggregation (`FILTER`, `date_trunc`), constraints, and what most production apps use | SQLite (simpler, one file, but weaker for concurrent writes); MongoDB (no schema, but our data is naturally a table) |
| **Steam's `filter=recent` with cursor pagination** | Newest-first order gives a stable cursor to follow page by page | `filter=all` sorts by helpfulness, which shifts while you page through it |
| **`ON CONFLICT DO NOTHING` on Steam's review ID** | Re-running a fetch never creates duplicates, in one statement | Check "does it exist?" before each insert: twice the queries, and two fetches at once could both insert |
| **Commit after every page** | A crash midway keeps everything fetched so far | One big transaction: all-or-nothing, so a failure at page 19 throws away 18 pages |
| **Retry only network errors, 429 and 5xx** | Those can fix themselves; a 404 never will | Retrying everything (wastes time on hopeless requests, which is what the Phase 1 code did) |
| **Honor `Retry-After`, capped at 60 s** | If Steam says how long to back off, that beats guessing; the cap stops one header from freezing a request | Always use our own backoff |

### Sentiment

| Choice | Why | Alternatives |
|---|---|---|
| **VADER** | No training, instant, explainable word by word, built for short informal text | TextBlob (similar idea, less tuned for social text); a transformer model like a fine-tuned RoBERTa (far more accurate on context and sarcasm, but slower and needs a GPU for speed); an LLM (best understanding, but costs per review) |
| **Remove BBCode tags and ♥ before scoring** | `[b]great[/b]` scored 0, and `this game is ♥♥♥♥` scored +0.96 because VADER reads Steam's profanity censor as hearts | Score raw text (measurably worse on Not recommended reviews) |
| **±0.05 thresholds** | VADER's authors recommend them | Tune them on our data, at the risk of overfitting to two games |
| **Store both score and label** | The score keeps the detail (for averages); the label is what the dashboard filters on | Store only the score and compute labels in every query |
| **Scoring is its own step** | Can re-score everything after changing the cleanup or thresholds, without re-fetching | Score inside the insert: simpler, but no way to redo scores |
| **Score in batches of 1,000, walking IDs in order** | Memory stays flat however many reviews there are; works for both "unscored only" and "rescore all" | Load everything at once (fine for 4,000 reviews, not for 4 million) |
| **`init.sql` re-runnable (`ADD COLUMN IF NOT EXISTS`)** | Adds new columns without deleting data | A migration tool like Alembic (better once there are many schema changes); wiping the database |

### API

| Choice | Why | Alternatives |
|---|---|---|
| **FastAPI** | Validation from type hints, automatic docs at `/docs`, little boilerplate | Flask (more manual validation); Django (much bigger, built for full websites) |
| **Plain (non-async) endpoints with psycopg** | Simpler code. FastAPI runs them in a thread pool, so a slow fetch doesn't block other requests | `async` endpoints with an async driver: more throughput, more complexity |
| **One connection per request** | Simple and isolated | A connection pool (`psycopg_pool`): faster under heavy load |
| **Fetch waits until done, max 5,000** | Simplest design: one request, one answer. The cap keeps the wait to about a minute | Background job + "status" endpoint: no waiting, but more moving parts. The right move for big fetches or many users |
| **Agreement counts neutral as a miss, plus a baseline** | Players can't vote neutral, so neutral is never "right". The baseline shows whether agreement beats a model that does nothing | Exclude neutral reviews (flatters the score: 86.2% vs 68.3% on all data) |
| **Trend months in UTC, with review counts** | Results don't depend on the server's time zone; counts show which months to trust | Server time zone; averages alone |
| **Page-number pagination, ties broken by ID** | Easy for a table with page numbers; the ID tie-breaker stops reviews posted in the same second from appearing on two pages | Keyset/cursor pagination: faster on deep pages and stable while data changes, but no "jump to page 7" |
| **`404` for a game with no reviews, empty list for a filter with no matches** | "This game isn't loaded" is an error; "no negative reviews" is a valid answer | Empty responses everywhere (the frontend couldn't tell the two apart) |
| **CORS for named origins from `.env`** | Only your frontend's address can call the API from a browser | `*` (any website could call it) |

### Infrastructure and tests

| Choice | Why | Alternatives |
|---|---|---|
| **Docker Compose** | `docker compose up` gives anyone the same database and API, no local Python or PostgreSQL setup | Install everything locally (what Phase 1–2 did on macOS: several manual steps) |
| **Dependencies copied before code in the Dockerfile** | Docker caches the slow `pip install` step, so a code-only change reuses it instead of reinstalling every package | Copy everything at once (every change reinstalls all packages) |
| **Tests use a real PostgreSQL test database** | Tests the actual SQL (`FILTER`, `date_trunc`, `ON CONFLICT`). A separate `_test` database keeps real data safe | Mock the database (would miss SQL bugs); SQLite (different SQL dialect) |
| **Steam faked in tests** | Fast, repeatable, works offline, and can simulate failures like 429s on demand | Call real Steam (slow, flaky, can't force errors) |
| **Shared `app` package for API and scripts** | One copy of the fetch and scoring logic | Duplicate code in scripts and API |
| **Separate dev requirements** | The Docker image doesn't carry test tools | One requirements file |

---

## 4. Key concepts, simply

**REST API / endpoint.** A URL your frontend can call. `GET` reads data, `POST` makes something happen (here: fetching reviews).

**HTTP status codes used here.**
- `200`: worked.
- `404`: not found (the game has no reviews).
- `422`: your input is invalid (FastAPI checks this automatically).
- `502`: Steam, a service we depend on, failed.
- `503`: our database is down.

**Idempotent.** Doing it twice has the same effect as doing it once. Fetching the same game twice doesn't duplicate reviews.

**Cursor pagination.** Steam doesn't let you ask for "page 7". Each response gives a bookmark (cursor) for where the next page starts.

**Offset pagination.** Our reviews endpoint uses `LIMIT 20 OFFSET 40` to get page 3. It's simple, but the database still walks past the skipped rows, so very deep pages get slower.

**Exponential backoff.** After a failure, wait 2 s, then 4 s, then give up. Waiting longer each time gives a struggling server room to recover.

**Rate limiting / `Retry-After`.** Servers limit how fast you can call them. A `429` means "slow down", and the `Retry-After` header can say for how long.

**VADER.**
- Each word in a list of ~7,500 words and emoticons has a human-rated score.
- Rules adjust the scores:
  - "not" flips a word.
  - "very" boosts the next word.
  - CAPS and "!!!" add emphasis.
  - Words after "but" count 1.5×, words before it 0.5×.
- The total is squashed into −1..+1, the **compound score**.
- It matches words; it doesn't understand meaning.

**Class imbalance and baselines.** If 98.1% of Portal 2 reviews are Recommended, a "model" that always says positive is right 98.1% of the time. Any accuracy number only means something compared to that **baseline**.

**Confusion table.** The grid `evaluate_sentiment.py` prints: for each true answer (vote), how the model labeled it. It shows *which* mistakes happen, not just how many.

**CORS.** Browsers block a web page on one address (`localhost:5173`) from reading responses from another (`localhost:8000`) unless the server says it's allowed. Tools like curl don't care. This is a browser safety rule.

**Dependency injection (`Depends`).** Endpoints don't open their own database connection; they ask for one. Tests swap in a test-database connection without changing endpoint code.

**Parameterized queries.** Values are sent separately from the SQL (`WHERE app_id = %s`), so input can never be run as SQL. This prevents SQL injection.

**Docker terms.**
- **Image:** a packaged app with everything it needs.
- **Container:** a running image.
- **Compose:** starts several containers together and connects them on a private network, where each service's name is its hostname.

**Mutation check.** Break the code on purpose and confirm a test fails. If none does, the tests aren't checking that code. This found a real gap: the summary test never exercised half of the agreement formula until its data was fixed.

---

## 5. Results so far

On Cities: Skylines II (2,000 newest reviews):

```
Steam vote               VADER: positive   neutral  negative
Recommended (1,501)                77.9%     16.0%      6.1%
Not recommended (499)              41.3%     15.6%     43.1%

Agreement:                    69.2%
Baseline:                     75.0%  (always guessing "Recommended")
```

- **VADER is below the do-nothing baseline** on both games: 69.2% vs 75.0% (Cities: Skylines II) and 67.3% vs 98.1% (Portal 2).
- **It misses most complaints.** It labeled 41.3% of Cities: Skylines II's Not recommended reviews as *positive*.
- **Why**, from a random sample of 10 disagreements:
  - 5 scored exactly 0 because VADER recognized no words: other languages, slang like "W", a Turkish dotless ı, or "barely playable".
  - 3 aimed sentiment at something else: praising the previous game, wishing the developers well, a joke.
  - 1 was sarcasm ("I'm lucky to even hit 30 FPS").
  - 1 was a real complaint from someone who still recommended the game.
- **Coverage:** the newest 2,000 reviews only span 3 months (Portal 2) and 4 months (Cities: Skylines II), so the trend is short until more is fetched.

---

## 6. Interview questions

**Walk me through the architecture.**
A FastAPI service and PostgreSQL, run together with Docker Compose. `POST /games/{id}/fetch` pulls reviews from Steam's API page by page, saves them without duplicates, and scores each one with VADER. Three `GET` endpoints serve a summary, a monthly trend, and filtered, paginated reviews to a React frontend. The fetching and scoring logic lives in one shared package that both the API and the command-line scripts use.

**What happens if you fetch the same game twice?**
Nothing bad. Each review has Steam's unique ID as the primary key, and inserts use `ON CONFLICT DO NOTHING`, so known reviews are skipped. The response's `new` count shows how many were actually added. A test covers this: the second fetch returns `new: 0`.

**How do you handle Steam failing or rate limiting you?**
- **Network errors, 429s and 5xx errors** are retried up to 3 times with exponential backoff. If Steam sends `Retry-After`, I wait that long instead, capped at 60 seconds.
- **Other errors, like a 404,** fail at once, because retrying can't fix them.
- **If it still fails,** the API returns `502`, so the client knows the problem is upstream. Pages already saved are kept and scored.
- **I pause 1 second between pages**, so I'm unlikely to be rate limited in the first place.

**Why VADER, and what are its limits?**
It needs no training data, scores 4,000 reviews in under a second, and every score can be explained word by word. That made it a good first model and benchmark. Its limit is that it only matches words. It can't handle:
- Sarcasm.
- Opinions aimed at something else ("the first game is better").
- Mixed reviews.
- Slang or other languages.

On our data it agrees with players 69.2% of the time on Cities: Skylines II, below the 75.0% baseline. The next step would be a transformer model fine-tuned on reviews, judged with the same evaluation.

**How do you know whether your sentiment model is any good?**
I compare its label to the player's own thumbs up/down, which is free labeled data. Raw agreement is misleading because most reviews are positive, so I always show the majority-class baseline next to it. I also break agreement down by class: VADER catches only 43.1% of Cities: Skylines II's Not recommended reviews as negative, and those are the reviews a dashboard most needs to surface.

**Isn't the thumbs-up vote a flawed ground truth?**
Yes. It's a recommendation, not a measure of the text's tone. "Nice game but too lag and crashes :(" is Recommended, yet the text is negative. So agreement can't reach 100% even for a perfect sentiment model. It's a proxy, but a consistent one, which is what you need to compare models.

**Why does the fetch request wait until it's done? How would you scale it?**
For a local tool, waiting is the simplest correct design. Fetching 2,000 reviews takes about 27 seconds, and I capped requests at 5,000. With many users or huge fetches, I'd make it a background job: `POST` returns `202` with a job ID right away, a worker (e.g. a task queue like Celery or RQ) does the fetching, and the client polls a status endpoint.

**Why offset pagination? What are the trade-offs?**
Page numbers are what a review table needs, and offset makes "page 7" trivial. The downsides:
- The database scans past all skipped rows, so deep pages get slower.
- If new reviews arrive while you're paging, items can shift between pages.

Keyset pagination ("give me 20 older than this ID") fixes both but can't jump to an arbitrary page. I sort by date and then by ID, so the order is always the same and no review appears twice.

**What is CORS and why did you need it?**
It's a browser rule. A page served from `localhost:5173` (the React dev server) can't read responses from `localhost:8000` unless the API sends headers allowing that origin. I allow only the origins listed in `.env`, not `*`, and tests check that another site gets refused.

**How do your tests avoid touching real data or the internet?**
- **Database:** they run against a separate `steam_reviews_test` database, created automatically and emptied before each test. FastAPI's dependency override points the endpoints at it.
- **Steam:** it's replaced with a fake that returns scripted responses. That's how I can test a 429 followed by success, or three 503s in a row, instantly and offline.
- **Checking the tests:** I broke the code on purpose to confirm tests fail. One break wasn't caught at first, which exposed weak test data that I then fixed.

**How does the API container find the database?**
Compose puts both containers on a private network where each service's name is its hostname, so the API connects to `db:5432`. `depends_on` with a health check makes the API wait until PostgreSQL actually accepts connections, not just until its container starts.

**Why does the trend only cover a few months?**
Each fetch starts from the newest review, and 2,000 reviews only reach back 3–4 months for these games. A longer trend needs a bigger fetch. Even better would be remembering the cursor where the last fetch stopped, so each fetch continues further back.

**How do you keep secrets out of the code?**
Credentials live in `.env`, which is git-ignored, with `.env.example` as a template. Docker Compose reads the same file. All SQL uses parameterized queries, so user input is never pasted into SQL.
