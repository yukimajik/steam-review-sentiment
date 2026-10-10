# How It Works

A learning guide to this project: what each piece does, how data moves through it, why it was built this way, and how to talk about it in an interview. Every number here comes from a real run on this project's data. That started as 2,000 reviews each of Portal 2 and Cities: Skylines II, and grew to 16,500 reviews from 15 games (fetched October 2026).

**Built so far:**
- Phase 1: fetch reviews into PostgreSQL.
- Phase 2: VADER sentiment, and measuring its accuracy.
- Phase 3: FastAPI backend in Docker, with tests.
- Phase 4: React dashboard.
- Then: search by game name instead of app ID.
- Then: an experiment comparing VADER with a transformer and a trained classifier.
- Then: the app switched from VADER to the trained classifier (TF-IDF + logistic regression).
- Then: sentiment around game updates. Updates come from each game's official Steam news, and the average sentiment in the 2 weeks before and after each one is compared. The timeline switched from months to weeks and marks the updates.
- Before that: a topic breakdown. Each review is tagged with the topics it mentions (performance, bugs, price/value, story, gameplay, graphics, multiplayer/servers, content/length) using keyword lists, and each topic gets its own sentiment.

---

## 1. What each file does

| File | What it does |
|---|---|
| `docker-compose.yml` | Starts two containers: `db` (PostgreSQL 17) and `api` (the FastAPI app). The API waits until the database is healthy. |
| `.env.example` | Template for `.env`, which holds the database password and settings. `.env` is git-ignored so secrets never get committed. |
| `db/init.sql` | Creates the `reviews` table, adds the sentiment columns, and creates the `review_topics` table. Runs automatically on a brand-new database and is safe to re-run on an existing one. |
| `backend/app/main.py` | The API: eight endpoints, CORS, input validation, and turning errors into the right HTTP status codes. |
| `backend/app/steam.py` | Talks to Steam: fetches reviews (following page cursors, or one day at a time), reads a game's official news, and searches the store by name. All share one retry function that respects rate limits. |
| `backend/app/updates.py` | Game updates: which news posts count as updates, grouping updates less than 2 weeks apart, fetching the reviews around each one, and the before/after numbers. |
| `backend/app/search.py` | Game search on top of Steam's store search: a one-hour cache and the typo fallback. |
| `backend/app/sentiment.py` | Cleans review text and scores it with the trained classifier, then turns the score into positive / neutral / negative. |
| `backend/app/topics.py` | The topic keyword lists. Cuts a review into parts (sentences, list items, and at "but"/"however"), finds the parts that mention each topic, and scores just those parts with the classifier. |
| `backend/app/sentiment_model.pkl` | The trained classifier (1.8 MB): the TF-IDF vocabulary, the word weights, and the neutral band. Built by `train_model.py`. |
| `backend/app/db.py` | Saves reviews (skipping duplicates), and scores and topic-tags unscored reviews in batches. Shared by the API and the scripts. |
| `backend/scripts/fetch_reviews.py` | Command-line version of fetching (without scoring). |
| `backend/scripts/score_sentiment.py` | Command-line scoring and topic tagging of unscored reviews; `--rescore` redoes all (after retraining the model or changing the topic keywords). |
| `backend/scripts/train_model.py` | Trains the classifier from the reviews in the database: a held-out check on 4 unseen games, then the final model on everything. |
| `backend/scripts/evaluate_sentiment.py` | Prints a detailed table of how the stored labels compare to players' votes. |
| `backend/experiments/compare_models.py` | The model comparison experiment: VADER vs. a pretrained transformer vs. TF-IDF + logistic regression, on games held out from training. Writes `results.md`. |
| `backend/experiments/requirements.txt` | The experiment's extra packages (VADER, PyTorch, transformers). The app and its Docker image don't use them. |
| `backend/experiments/results.md` | The latest comparison report, written by the script. |
| `backend/tests/` | 140 pytest tests: `test_api.py` (endpoints), `test_search.py` (game search), `test_steam.py` (retries and errors), `test_sentiment.py` (the classifier), `test_topics.py` (topic keywords and per-topic sentiment), `test_updates.py` (update detection, windows, and the update endpoints), plus shared setup in `conftest.py` and `helpers.py`. |
| `backend/Dockerfile` | Recipe for the API's container image. |
| `backend/requirements.txt` / `requirements-dev.txt` | Python packages for the app / extra ones for tests. |
| `pytest.ini` | Tells pytest where the code and tests live. |
| `frontend/src/App.tsx` | The dashboard page: the picked game (name, cover, app ID), loading its data, the fetch button, and which state to show (loading, not stored, error, ready). |
| `frontend/src/api.ts` | Calls the API, mirrors its response shapes as TypeScript types, and turns failures into messages a person can act on. |
| `frontend/src/format.ts` | Number, date and score formatting, sentiment colors and labels, topic names, and stripping Steam's formatting tags for display. |
| `frontend/src/components/` | `GameSearch` (the search box and dropdown), `SummaryCards`, `SentimentPie`, `TrendChart`, `TopicBreakdown` (the topic chart and example excerpts), `UpdateShifts` (before/after numbers around updates, and the button that fetches their reviews), `ReviewList`: one file per part of the page. |
| `frontend/src/index.css` | All styling: color tokens, layout, and the phone/tablet/desktop breakpoints. |
| `frontend/package.json` | Frontend dependencies (React, Recharts, Vite, TypeScript, Oxlint) and scripts (`dev`, `build`, `lint`). |

### The `reviews` table

| Column | Meaning |
|---|---|
| `recommendation_id` | Steam's unique ID for the review (primary key, so duplicates are impossible) |
| `app_id` | Which game |
| `review_text` | What the player wrote |
| `voted_up` | The player's thumbs up (Recommended) or down (Not recommended) |
| `playtime_at_review_minutes`, `helpful_votes`, `created_at` | Extra details from Steam |
| `sentiment_compound` | The model's score, from −1 (surely Not recommended) to +1 (surely Recommended): 2 × P(Recommended) − 1. Named after VADER's "compound" score, which it held originally. |
| `sentiment_label` | `positive`, `neutral` or `negative`, derived from the score |

### The `game_updates` and `update_review_days` tables

- **`game_updates`**: one row per news post that counts as an update. Columns: Steam's post ID (`gid`), `app_id`, `title`, `url`, and `posted_at`. It's replaced each time the news is read, so a post that no longer counts disappears.
- **`update_review_days`**: `(app_id, day)` for every day whose reviews were fetched for the comparison. A day shared by two updates is fetched once, and an interrupted fetch resumes at the first missing day.

### The `review_topics` table

One row per review per topic it mentions. A review that mentions nothing has no rows.

| Column | Meaning |
|---|---|
| `recommendation_id` | Which review (deleting the review deletes its rows) |
| `topic` | `performance`, `bugs`, `price`, `story`, `gameplay`, `graphics`, `multiplayer` or `content` |
| `excerpt` | The parts of the review that mention the topic, joined with " … " |
| `sentiment_score`, `sentiment_label` | The classifier's verdict on the excerpt alone: positive = praise, negative = complaint |

---

## 2. How data flows

### Fetching a game: `POST /games/620/fetch?max_reviews=2000`

1. **Validation.** FastAPI checks the app ID is a positive number that fits the database column, and `max_reviews` is 1–5,000. Anything else gets a `422` before any code runs.
2. **Connection.** `get_conn` opens a database connection for this request.
3. **First page.** `steam.fetch_page` asks Steam for 100 reviews with cursor `*` ("start from the newest").
4. **Save.** `steam.to_row` picks out the fields we store, and `db.save_reviews` inserts them with `ON CONFLICT DO NOTHING`, so reviews we already have are skipped. Each page is committed immediately.
5. **Next pages.** Steam's response includes a cursor pointing at the next page. We wait 1 second (to be polite) and ask again, until we hit `max_reviews`, get an empty page, or Steam repeats the cursor.
6. **If Steam fails.** Network errors, rate limits (`429`) and server errors (`5xx`) are retried up to 3 times. Anything else (like `404`) fails at once. If it still fails, the reviews already saved get scored and the API returns `502`.
7. **Nothing found.** If Steam had zero reviews, the API returns `404` saying the app may not exist or has no reviews yet. Steam gives the identical answer ("success", zero reviews) for an app ID that doesn't exist and for a real app with no reviews, such as a game demo, so the API can't tell which it is.
8. **Scoring and topics.** `db.score_reviews` reads this game's unscored reviews 1,000 at a time.
   - `sentiment.score_many` cleans the texts and scores the whole batch with the classifier in one call. Scores and labels are written back.
   - `topics.tag_many` finds the topics in each review and scores each topic's excerpt, again in one call. Old topic rows for these reviews are deleted and the new ones inserted, in the same transaction as the scores.
9. **Response.** `{"fetched": 2000, "new": 2000, "scored": 2000}`. In real runs this took 26.4 and 27.7 seconds, almost all of it waiting on Steam. Re-scoring all 16,500 stored reviews took 3.1 seconds.

### Reading: summary, trend, reviews

- **Summary** runs one SQL query that counts everything at once (`count(*) FILTER (WHERE ...)`): totals per label, Recommended votes, and agreements. Python turns the counts into percentages.
- **Trend** groups reviews by the week they were posted (Monday to Sunday, UTC) and averages the score. Weeks with no reviews are simply missing, and the chart shows them as gaps.
- **Reviews** runs two queries: one counts matching reviews (for page numbers), one fetches the requested page, newest first.
- **Topics** runs three queries: the number of scored reviews; praise, neutral and complaint counts per topic; and the top 3 praise and complaint excerpts per topic, picked with a window function (`row_number() OVER (PARTITION BY topic, label ...)`). Python fills in zeros for topics nobody mentions and sorts by mentions.
- All four only look at **scored** reviews and return `404` if the game has none.

### Comparing updates: `POST /games/{id}/updates/fetch`, then `GET /games/{id}/updates`

1. **News.** The API reads the game's last 100 official announcements from `ISteamNews/GetNewsForApp` (official posts only, no press articles) and keeps the ones that count as updates (see design choices). They replace the game's rows in `game_updates`.
2. **Grouping.** Update posts less than 14 days after a group's first post join that group, so a hotfix two days after a patch doesn't get its own, mostly overlapping, comparison. Only groups from the last 12 months count.
3. **Which update next.** Groups whose 14 days "after" aren't over yet are "too recent". Of the rest, only the 10 most recent are used. The newest one still missing reviews is fetched by this request.
4. **Reviews.** For each of the 28 days around it (14 before, 14 after; the update's own day is skipped because it mixes both), one request asks Steam's review API for that day's reviews, up to 100. Days already fetched are skipped. Each day's reviews are saved like any others and the day is recorded, with a 1-second pause between requests. Then the new reviews are scored and topic-tagged.
5. **Response.** `{"fetched_day": "2026-09-01", "new_reviews": 528, "remaining": 1}`. The page calls again until `remaining` is 0. In real runs one update took 33–36 s, or 18.9 s when half its days were already fetched for a neighboring update.
6. **Rate limits.** If Steam keeps answering 429 after the usual retries, the API answers `429` with `Retry-After: 60`; the days already fetched are kept. The page waits a minute and carries on.
7. **Comparing.** `GET /updates` reads only the database. For each group it counts reviews, averages the score, and works out the share of Recommended votes in the 14 days before and after, then ranks the 3 biggest rises and drops among updates with at least 30 reviews on each side.

### The command-line scripts

They call the same `app` functions as the API, so there's one copy of the logic. `fetch_reviews.py` + `score_sentiment.py` together do what the fetch endpoint does.

### In the browser

1. You type part of a game's name. `GameSearch` waits until you pause typing (300 ms) and calls `/search` (described in the next section). It shows up to 10 matches with covers. Picking one hands its app ID, name and cover to `App`.
2. `App` calls `/summary`, `/trend`, `/topics` and `/updates` at the same time (`Promise.all`) and shows gray placeholder shapes meanwhile.
3. **404** means the game isn't stored. The page offers "Fetch reviews from Steam", which calls `POST /fetch?max_reviews=1000`. In a real run that took 12.8 seconds, then the dashboard loaded.
4. **Any other error** shows a message saying what to do (start the API, start the database, try again later) with a "Try again" button.
5. **Success** draws the summary cards, the pie, the weekly line chart with update markers, the update section and the topic section. `ReviewList` then loads its own data: 10 reviews per page, newest first, optionally filtered by sentiment.
6. **The update section** offers "Find updates", or "Fetch reviews around N updates" with an estimated time. While it runs it shows "update 2 of 5", pauses for a minute if Steam rate limits, and reloads the dashboard when done. Picking another game stops it.
7. **The topic section** starts on the most-mentioned topic. Clicking a bar or a topic button shows that topic's praise and complaint excerpts.
8. **Changing the filter or page** keeps the current reviews on screen, faded, until the new ones arrive, so nothing jumps.

### Searching for a game: `GET /search?q=cyberpnk`

1. **Validation.** The query is lowercased and spaces are collapsed. Fewer than 2 or more than 100 characters returns `422`, without asking Steam.
2. **Cache.** If the same search was answered within the last hour, the answer comes from memory. In a real run, "Portal" took 0.29 s from Steam, and the repeat search "portal" took 0.006 s from the cache.
3. **Steam.** Otherwise the backend calls Steam's store search (`store.steampowered.com/api/storesearch`). It keeps only `app` results, because packages and bundles have IDs that aren't app IDs.
4. **Typo fallback.** If nothing matches, it drops the last letter and asks again, up to 3 times and never below 3 letters.
   - In real runs, "cyberpnk" became "cyberp", which found Cyberpunk 2077.
   - The response's `matched_query` says which search produced the results, so the dropdown can show "No exact match for 'cyberpnk'. Showing results for 'cyberp'".
5. **Failures.** Search waits at most 5 s per try and tries twice, giving up much sooner than fetching does. If Steam still fails, the API returns `502`.

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
| **TF-IDF + logistic regression, trained on our reviews** (replaced VADER) | On 4 games it never trained on: 85.7% accuracy vs. VADER's 83.3% (baseline 81.0%), and it catches far more complaints. Fits the free tier (the API uses 120 MiB with it loaded) and scores ~25,000 reviews/s | VADER (no training, but its general word list misreads gaming words); the twitter-roberta transformer (best at catching complaints, but peaked at 1.7–2.5 GB); an LLM (costs per review) |
| **It predicts the player's vote, not the text's tone** | `voted_up` is the only label we have at scale, so the model learns what recommending players write. "great game, too bad the servers never work" comes out negative | Hand-labeling tone (slow, and our judgement) |
| **Neutral band: P(Recommended) between 0.39 and 0.61** | The narrowest band where the remaining labels are right at least 90% of the time, chosen with out-of-fold predictions so it never sees test data. On unseen games those labels were 90.9% accurate | Two labels only (no neutral, but a two-slice pie and no Neutral filter); a band picked by eye |
| **No recognizable words → neutral** | Empty, emoji-only or other-language reviews would otherwise get the model's built-in lean toward Recommended, which isn't evidence. 239 of 4,000 held-out reviews were like this. VADER also scored these 0 | Let the lean decide (raises agreement, but labels guesses as "positive") |
| **Model saved as a pickle in the repo, with the scikit-learn version checked on load** | The API just loads a 1.8 MB file; `train_model.py` rebuilds it. A pickle only loads correctly with the scikit-learn version that made it, so a mismatch fails loudly | Training at startup (needs the database and ~25 s on every boot); exporting weights to JSON (no scikit-learn needed, but re-implementing TF-IDF exactly) |
| **Remove BBCode tags and ♥ before scoring** | Formatting tags and Steam's profanity censor aren't the reviewer's words. (With VADER, `this game is ♥♥♥♥` scored +0.96 because it read the hearts as love) | Score raw text |
| **Store both score and label** | The score keeps the detail (for averages); the label is what the dashboard filters on | Store only the score and compute labels in every query |
| **Scoring is its own step** | Can re-score everything after changing the cleanup or thresholds, without re-fetching | Score inside the insert: simpler, but no way to redo scores |
| **Score in batches of 1,000, walking IDs in order** | Memory stays flat however many reviews there are; works for both "unscored only" and "rescore all" | Load everything at once (fine for 4,000 reviews, not for 4 million) |
| **`init.sql` re-runnable (`ADD COLUMN IF NOT EXISTS`, `CREATE TABLE IF NOT EXISTS`)** | Adds new columns and tables without deleting data | A migration tool like Alembic (better once there are many schema changes); wiping the database |

### Topics

| Choice | Why | Alternatives |
|---|---|---|
| **Keyword lists** | Simple, instant, no memory cost, and you can always see *why* a review got a tag. A good first version to measure smarter methods against | **Trained topic classifier** (one TF-IDF model per topic): learns words we didn't list, but needs hundreds of hand-labeled reviews per topic, and we have none. **Zero-shot transformer** ("is this about performance?"): no labels needed and understands paraphrases, but the transformer we measured peaked at 1.7–2.5 GB vs. the free tier's 512 MB. **Embeddings + similarity**: catches "my GPU is crying", but needs a neural model too. **Topic modeling** (LDA, BERTopic): finds its own topics, which won't line up with the 8 we want and need naming by hand. **An LLM API**: best with mixed reviews and sarcasm, but costs money per review, needs an API key, and adds rate limits |
| **Every keyword checked against the stored reviews; lookalikes dropped** | Favors tags that are right over catching everything. Dropped or narrowed after reading real matches: "refund" (mostly "I'd refund if I could", a verdict, not price), a bare "worth" ("worth every hour"), a bare "hours" (playtime), "ping" (the in-game marker), "optimistic", "performances" (acting), "graphics card", "as of writing this", "content creators", "freezer" | Long lists of every related word: more matches, many of them wrong |
| **Whole words only, any case** | "lag" mustn't match "flagship", or "bug" match "debug" | Plain substring search |
| **Each topic's sentiment comes from only the parts that mention it** | In "Great game, but it runs terribly", performance is a complaint even though the review is positive. 27.3% of topic tags got a different label than the whole review, and 397 Recommended reviews contain a complaint this way | The whole review's label (hides exactly those complaints); the player's vote (it's about the whole game too) |
| **Cut at sentence ends, line breaks, list items, semicolons, "but" and "however"** | "X, but Y" is the most common way one sentence mixes praise and a complaint | Sentences only (keeps "great game but laggy" together); a proper sentence parser like spaCy (another big dependency) |
| **The same classifier scores the excerpts** | No new model, no extra memory | VADER for excerpts (scores tone, but misreads gaming words); a model trained on hand-labeled excerpts (better, needs labels) |
| **Unticked boxes in Steam's checkbox template are ignored** | In a template like "☐ Too much grind / ☑ Average grind", the unticked options aren't the reviewer's opinion. 19 of the 17,554 stored reviews use it | Keep them (would tag complaints nobody made) |
| **Tags stored in a table, computed while scoring** | The topic endpoint is then a cheap SQL query (21–56 ms in real runs), which matters on a 0.1-CPU server. Changing a keyword means re-running `score_sentiment.py --rescore` | Computing topics on every request: always uses the latest keywords and needs no table, but re-reads and re-scores every review on every page load |
| **A new `sentiment_score` column instead of reusing the name `sentiment_compound`** | "compound" is a VADER term that no longer fits; the reviews table keeps its old name only to avoid breaking the API | Copying the old name for consistency |

### Updates

| Choice | Why | Alternatives |
|---|---|---|
| **Updates from `ISteamNews/GetNewsForApp`, official posts only** | Free and needs no key. The feed also carries press articles (e.g. PlayGround.ru about the Elden Ring film), so it's filtered to the game's own announcements | Steam's store "events" page (labels post types, but undocumented and untested here); a hand-made list of patch dates |
| **An update is: Steam's `patchnotes` tag, *or* a title with patch/hotfix/changelog/release notes/a version number, *or* "update"/"season" with "now live"/"out now"; minus test-server, preview and announcement posts** | Checked against every stored game. The tag alone missed whole games (Black Myth: Wukong tags none of its "1.0.21.23831 Patch Notes" posts). "update" alone caught dev blogs ("Blog Update #50"). "Introducing Update Ver. 1.041 — Available Wednesday" was posted 8 days before that update | The tag only; every official post (includes sales, merchandise, Steam Awards) |
| **Fetch reviews around each update, one day at a time, up to 100 per day** | The newest 1,000 reviews span only 7–37 days for most games, so only 4 updates in all 16 games had both windows covered. Steam's review API accepts a date range (used by the store's own filter, not documented); asking day by day keeps every day represented, instead of only the last days of each window | Only stored reviews (almost nothing to compare); all reviews in each window (up to ~4,000 per update for big games); the newest N of each window (biased toward its end) |
| **Check the date range was honoured** | It's undocumented, so it could change. If Steam sends reviews and none are from the requested day, that's an error, not data | Trust it |
| **The update's own day is left out** | It mixes reviews from before and after the release | Split that day at the post's exact time (the 100-per-day sample doesn't spread evenly across hours) |
| **Updates less than 14 days after a group's start are merged into it** | Otherwise a hotfix's "before" would be mostly the main patch's "after". Updates 14–28 days apart still overlap partly; that's unavoidable with 2-week windows on games that update often | Every post separately; requiring 28-day gaps (drops many updates) |
| **Last 12 months, at most the 10 most recent, only once the 2 weeks after are over** | Each update costs 28 requests (about 35 s). A half-finished "after" window would compare 14 days with a few | All updates (minutes per game, and rate limits) |
| **Only updates with 30+ reviews on each side are ranked** | Averages of a handful of reviews swing wildly, and a "biggest shift" list would otherwise be dominated by them | No minimum; a statistical test (more honest about noise, but more to explain; not asked for) |
| **Show the share of Recommended votes next to the model's score** | The votes are the players' own answer, from the same reviews, so they're a free check on the model. For PAYDAY 3 the two moved in opposite directions for 4 of 10 updates | Model score only |
| **Wording: "before / after", never "impact" or "caused"** | Sales, events, new seasons and new players arrive around updates, so the numbers can't separate an update's effect from everything else | A causal design (e.g. comparing with similar games that didn't update), which is a much bigger project |
| **One update per request; the page loops and shows "update 2 of 5"** | Each request stays well under a minute, and progress is visible | One request for everything (several minutes of a silent spinner); a background job queue (more moving parts) |
| **When Steam rate limits: answer 429 with `Retry-After`, the page waits a minute and continues** | Happened for real after about 125 requests in 2.5 minutes. Steam sent no `Retry-After`, and it lifted within 91 s of probing. Fetched days are kept | Slowing every request down (we don't know Steam's limit, and guessing would make every fetch slower) |
| **Fetched days recorded in their own table** | An interrupted fetch resumes, and days shared by neighboring updates aren't fetched twice | Recording whole updates as done (breaks when groups change as new posts arrive) |
| **The extra reviews go into the normal `reviews` table** | They're scored and topic-tagged like the rest. The trade-off: the summary, pie, topics and review list now include them, so they describe all stored reviews, not just the newest | A separate table used only for the comparison |
| **Scores shown with 3 decimals here** | Shifts are often small; with 2 decimals, "+0.52 → +0.54 (+0.01)" looked wrong | 2 decimals as elsewhere |

### API

| Choice | Why | Alternatives |
|---|---|---|
| **FastAPI** | Validation from type hints, automatic docs at `/docs`, little boilerplate | Flask (more manual validation); Django (much bigger, built for full websites) |
| **Plain (non-async) endpoints with psycopg** | Simpler code. FastAPI runs them in a thread pool, so a slow fetch doesn't block other requests | `async` endpoints with an async driver: more throughput, more complexity |
| **One connection per request** | Simple and isolated | A connection pool (`psycopg_pool`): faster under heavy load |
| **Fetch waits until done, max 5,000** | Simplest design: one request, one answer. The cap keeps the wait to about a minute | Background job + "status" endpoint: no waiting, but more moving parts. The right move for big fetches or many users |
| **Agreement counts neutral as a miss, plus a baseline** | Players can't vote neutral, so neutral is never "right". The baseline shows whether agreement beats a model that does nothing | Exclude neutral reviews (flatters the score: 86.2% vs 68.3% on all data) |
| **Trend weeks in UTC, with review counts** | Results don't depend on the server's time zone; counts show which weeks to trust. Weeks replaced months so a 2-week before/after can be seen on the chart | Months (too coarse to see an update's effect window); days (too noisy with ~10 reviews a day for smaller games) |
| **Page-number pagination, ties broken by ID** | Easy for a table with page numbers; the ID tie-breaker stops reviews posted in the same second from appearing on two pages | Keyset/cursor pagination: faster on deep pages and stable while data changes, but no "jump to page 7" |
| **Topics: all 8 always returned, most mentioned first, with counts rather than percentages** | The frontend can show "nobody mentions multiplayer" without guessing which topics exist, and computes shares from the counts and the total | Only topics with mentions; percentages from the API |
| **Topic examples: up to 3 per side, most helpful votes first, then most confident; neutral never shown** | Helpful votes are other players vouching for a review; confidence breaks ties among the many reviews with no votes yet | Random examples; most recent; longest |
| **`404` for a game with no reviews, empty list for a filter with no matches** | "This game isn't loaded" is an error; "no negative reviews" is a valid answer | Empty responses everywhere (the frontend couldn't tell the two apart) |
| **CORS for named origins from `.env`** | Only your frontend's address can call the API from a browser | `*` (any website could call it) |

### Choosing a sentiment model (experiment)

| Choice | Why | Alternatives |
|---|---|---|
| **Steam's `voted_up` as the answer key** | Free, and labeled by the reviewer themselves. It's a recommendation, not a tone rating, so no model can reach 100% | Labeling reviews by hand (slow, and it's our judgement, not the player's) |
| **Test set = whole games the classifier never trained on** | A trained model can learn game-specific words ("Todd", "Starfield"). Testing on unseen games measures what the app does: score games it has never seen | A random split of all reviews (would flatter the trained model) |
| **Fetched 10 more games, 6 of them "Mixed"** | Before, only 681 of 6,500 reviews were Not recommended, 499 of them from one game. After: 3,250 of 16,500, from 15 games | Testing on what we had (too few complaints to measure) |
| **Accuracy reported with baseline, balanced accuracy and per-class recall** | 81.0% of test reviews are Recommended, so accuracy alone barely separates the models; how many complaints each catches does | Accuracy only |
| **Each model in its own fresh process** | Peak memory is measured per model, not mixed together | Measuring everything in one process |
| **TF-IDF classifier weighted toward the rarer class, settings chosen by cross-validation grouped by game** | Without weighting it would lean toward always saying Recommended; grouping by game keeps the tuning honest too | Default settings; tuning on the test set (cheating) |

### Infrastructure and tests

| Choice | Why | Alternatives |
|---|---|---|
| **Docker Compose** | `docker compose up` gives anyone the same database and API, no local Python or PostgreSQL setup | Install everything locally (what Phase 1–2 did on macOS: several manual steps) |
| **Dependencies copied before code in the Dockerfile** | Docker caches the slow `pip install` step, so a code-only change reuses it instead of reinstalling every package | Copy everything at once (every change reinstalls all packages) |
| **Tests use a real PostgreSQL test database** | Tests the actual SQL (`FILTER`, `date_trunc`, `ON CONFLICT`). A separate `_test` database keeps real data safe | Mock the database (would miss SQL bugs); SQLite (different SQL dialect) |
| **Steam faked in tests** | Fast, repeatable, works offline, and can simulate failures like 429s on demand | Call real Steam (slow, flaky, can't force errors) |
| **Shared `app` package for API and scripts** | One copy of the fetch and scoring logic | Duplicate code in scripts and API |
| **Separate dev requirements** | The Docker image doesn't carry test tools | One requirements file |
| **The image listens on `$PORT`, defaulting to 8000** | Hosts like Render choose the port (Render uses 10000) and pass it in `PORT`; locally nothing changes. Started with `exec` so uvicorn receives the shutdown signal directly | Hard-coding 8000 and configuring the host to match |

### Frontend

| Choice | Why | Alternatives |
|---|---|---|
| **Vite + React + TypeScript** | Vite starts instantly and reloads on save; TypeScript catches mistakes like a misspelled API field at build time | Create React App (no longer maintained); Next.js (server rendering we don't need); plain JavaScript |
| **Recharts** | Declarative React components for charts, with tooltips and responsive sizing built in | Chart.js (not React-native); D3 (full control, much more code) |
| **Blue / gray / red for positive / neutral / negative** | Sentiment is an *ordered* scale, so it gets a diverging palette: opposite poles plus a neutral midpoint. Checked with a script, not by eye: worst colorblind separation ΔE 8.7 (target ≥ 8), every color ≥ 3:1 contrast | Green/red (the classic pair red-green colorblind readers can't separate); three unrelated hues (hides the order) |
| **Legend with values next to the pie, data table under the line chart** | Every number is readable without hovering, and identity never relies on color alone | Tooltips only (hidden on touch screens and to screen readers) |
| **Line chart's y-axis fixed at −1 to +1, with a line at 0** | Shows where sentiment really sits on the model's scale. A zoomed-in axis would make a 0.35 → 0.38 wobble look dramatic | Auto-scaled axis |
| **Plain CSS with variables, no UI library** | Small, readable, nothing to learn beyond CSS; colors defined once | Tailwind; a component library like MUI |
| **Results tagged with the request they answer** | "Loading" is derived (latest result isn't for the current request), and a slow old response can never overwrite a newer one | Setting a `loading` flag inside the effect (an extra render, and the linter warns about it) |
| **`AbortController` on every request** | Searching again cancels the old request instead of racing it | Ignoring stale responses after they arrive |
| **"Server is waking up" note after 5 s of loading** | On Render's free plan the API sleeps without visitors and takes about a minute to wake; without the note, visitors would stare at placeholders and assume it's broken | A fixed loading spinner with no explanation; paying for an always-on server |
| **Search by name using Steam's store search** | Checked with real calls. The full app list (`ISteamApps/GetAppList`) now returns 404 "Method not found". Its replacement (`IStoreService/GetAppList`) needs a Steam Web API key, a new table and a refresh job, and has no covers for newer games. The store search needs none of that, ranks popular games first, and includes cover URLs | The full app list in our database: offline, fuzzy search under our control, but a secret key and much more machinery |
| **Search goes through our backend** | Steam's store search sends no CORS header, so a browser couldn't read its answers directly anyway. The backend also caches, retries, and hides an undocumented endpoint's format from the frontend | Calling Steam from the browser (blocked by CORS) |
| **Debounce of 300 ms, at least 2 characters** | Typing "hollow knight" sent 1 request, not 13 | Searching on every keystroke; a search button |
| **One-hour in-memory cache, at most 1,000 searches** | Repeated searches are instant and don't touch Steam; the cap keeps memory bounded | No cache; Redis (shared across servers, but another service to run) |
| **Typo fallback: drop the last letter, up to 3 times** | Steam matches word beginnings but not typos inside words. Fixed `cyberpnk`, `hollow knigt` and `stardw` in real tests | Plain "no results" message; fuzzy matching (needs the full list) |
| **DLC, demos and soundtracks shown** | Steam labels them like games; hiding them means guessing from names, or 10 extra calls per search | Filtering by words like "Soundtrack" |
| **Accessible combobox** | Keyboard (↑/↓/Enter/Esc), screen readers hear "10 games found", 48 px tall options for touch | A plain list of links |
| **Search disabled during a fetch** | The fetch result can't land on a different game than the one shown | Allowing it and tracking which game each fetch belongs to |
| **Steam's formatting tags stripped for display** | `[spoiler]...[/spoiler]` showed up on the first page of Portal 2 reviews; same tag list the scorer uses | Show raw text; render the formatting (more code, and spoilers would need a reveal button) |
| **Frontend runs with `npm run dev`, not in Docker yet** | Instant reloads while building; it can join Compose later | An nginx container serving the built files |
| **Topic chart: horizontal bars, complaints left in red and praise right in blue, as a share of all reviews** | Answers "what do players like and complain about most" in one view. Both sides use the same scale so they compare fairly, and topics are sorted by how often they come up | Stacked 100% bars per topic (hide how often a topic comes up); two separate charts (harder to compare a topic's two sides) |
| **Pick a topic by clicking its bar or a topic button** | Bars are quick with a mouse; the buttons also work with a keyboard and screen readers, and show which topic is selected. The selected topic's bars stay solid and the rest fade | A dropdown; a separate topic filter on the review list (all matching reviews with paging, but another filter to manage) |
| **Topics loaded with the summary and trend in one `Promise.all`** | One loading state for the whole dashboard; the data doesn't change while you look at it | Loading inside the component like `ReviewList` (its own spinner and error, but more code) |
| **One 648 kB bundle (190 kB gzipped), mostly Recharts** | Fine for a local dashboard | Load the charts separately with `import()` to make first paint faster |

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

**VADER** (the app's original model).
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

**Single-page app (SPA).** One HTML page; JavaScript fetches data from the API and redraws parts of the page, instead of the server sending a new page for every click.

**React state and effects.** State is data that, when it changes, makes React redraw. An effect runs after a redraw. Here, effects load data whenever the app ID, filter or page changes.

**Race conditions.** If you search 620 and then quickly 949230, the 620 answer might arrive last. The page cancels old requests (`AbortController`) and tags results with the request they answer, so the old answer is never shown.

**Responsive design.** One layout that adapts. Below 640px everything is one column, at 640px the cards go side by side, at 900px the two charts sit side by side. Checked at 375px (phone), 768px (tablet) and 1280px (desktop) with no sideways scrolling.

**Held-out test set and data leakage.** You test a model on examples it never trained on. Otherwise you're grading it on answers it has memorized. Here the held-out examples are whole games, so game-specific words can't leak from training into the test.

**Recall and balanced accuracy.** *Recall* for a class is the share of that class the model catches. "Not recommended caught: 50.5%" means VADER finds half the complaints. *Balanced accuracy* averages the two recalls, so a model can't score well just by always picking the common answer.

**TF-IDF + logistic regression.**
- TF-IDF turns each review into numbers: how often each word or word pair appears, weighted down when it's common across all reviews.
- Logistic regression learns a weight per word. "refund" pushes toward Not recommended, "masterpiece" toward Recommended.
- It's simple, fast and small, but it only knows words it saw in training.

**Transformer.** A neural network (here RoBERTa, trained on tweets) that reads words in context. It can tell that "insane boss fights" is praise. The cost is 501 MB of weights and slow processing without a GPU.

**Debouncing.** Waiting until the user pauses typing before doing the work. Each keystroke restarts a short timer, and only when it runs out does the search happen.

**Caching with expiry.** Remembering answers so repeat questions are instant. Each entry expires after an hour, so results can't get too old, and the oldest entries are dropped once there are 1,000, so memory can't grow forever.

**CORS, from the other side.** Our API sends CORS headers so our page can read it. Steam's store search doesn't, so no other website's page can read it. A server isn't a browser, so our backend can call Steam freely.

**Keyword matching with word boundaries.** A regular expression like `(?<!\w)lag(?!\w)` matches "lag" only when no letter or digit touches it on either side, so "flagship" doesn't count.

**Precision and recall, for tags.** *Precision*: of the reviews tagged "bugs", how many really talk about bugs. *Recall*: of the reviews that talk about bugs, how many got tagged. Keywords tend to have good precision and poor recall: they're usually right when they fire, but miss everything said in other words.

**Aspect-based sentiment.** Instead of one feeling per review, one feeling per thing the review talks about (its *aspects*: performance, story, ...). A review can love the story and hate the servers.

**Before/after is not cause and effect.** Two numbers measured before and after an event differ for many reasons: a sale bringing new players, a seasonal event, a review bomb, or plain chance. Showing a cause needs a comparison that holds everything else equal, such as similar games that didn't update at the same time. That's why the dashboard only reports the numbers.

**Sampling.** On busy days only the newest 100 reviews are fetched, so that day is represented by a sample from its later hours. It's a sample, not the whole day, which matters for games with more than 100 English reviews a day.

**Rate limits, seen from our side.** When Steam answers `429 Too Many Requests` without saying how long to wait, the polite thing is to stop, keep what you have, and try again later, not to keep hammering it.

**Skeletons vs. fading.** Gray placeholder shapes on the first load tell you what's coming. On later loads (new page, new filter), the old content stays and fades, because swapping it for placeholders would make the page jump.

## 5. Results so far

### With VADER (the original model)

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

### Sentiment model comparison

All numbers below are from `backend/experiments/results.md`.
- **Test set:** 4,000 reviews of 4 games the classifier never saw (Starfield, Rust, Black Myth: Wukong, Stardew Valley).
- **Answer key:** each player's own `voted_up`.
- **Baseline:** always guessing Recommended scores 81.0%.

| | Accuracy | Not recommended caught | Speed (this Mac) | Peak memory |
|---|---|---|---|---|
| VADER (previous) | 83.3% | 50.5% | 2,797 reviews/s | 50 MB |
| Transformer (twitter-roberta) | 83.8% | **84.6%** | 36 reviews/s | **1,682 MB** (1,982 and 2,499 MB in two earlier identical runs) |
| TF-IDF + logistic regression | **85.7%** | 77.5% | 24,832 reviews/s | 153 MB |

- **The bug check found no bug.** All 6,500 stored labels matched their scores, and re-scoring reproduced every stored value. The mislabels come from VADER's general-purpose word list: "insane", "fights" and "combat" count as negative, and "sick" too.
- **VADER catches only half the complaints.**
- **The transformer understands context best.** It scored "Zero regrets… insane boss fights" at +0.98. But it misreads gamer sarcasm ("10/10 would get scammed again" came out negative). It also peaked at 1.7–2.5 GB across three runs, 3–5× Render's free plan (512 MB).
- **The trained classifier is the most accurate, small and fast.** It learned gaming slang ("this game is sick" came out positive). But it predicts the *vote*, not the text's tone: "great game, too bad the servers never work" came out negative.

### After switching to the classifier

The training script's held-out check, with the app's three labels on the same 4 unseen games, compared with VADER's stored labels on those games:

| On 4 games the model never trained on | VADER | Trained classifier |
|---|---|---|
| Agreement (neutral counts as a miss) | 65.1% | **68.8%** |
| Labeled neutral | 21.3% | 24.4% |
| Accuracy of positive and negative labels | 82.6% | **90.9%** |
| Not recommended reviews labeled negative | 49.3% | **63.9%** |

- **The dashboard's numbers for the 15 stored games are optimistic,** because the final model trained on them. On all of them together, agreement is 79.8%, and 87.5% of Not recommended reviews are labeled negative. For a newly fetched game, expect numbers like the held-out check above.
- **Running it in the API:** memory went from about 50 MiB to **120 MiB** with the model loaded, well inside the free tier's 512 MB. The image is 637 MB.

### Topic breakdown

Measured on all 17,554 stored reviews from 16 games (the 15 above plus Elden Ring).

**Coverage.**
- **27.2% of reviews mention at least one topic.**
- **Most of the rest are very short:** 67.1% of the 12,776 untagged reviews are under 10 words ("hell yeah", "Masterpiece!").
- **Among reviews of 20 or more words, 62.2% get a tag.**

| Topic | Mentions | Praise | Neutral | Complaints |
|---|---|---|---|---|
| Gameplay | 1,983 | 62.3% | 22.8% | 14.8% |
| Story | 1,438 | 70.8% | 18.6% | 10.6% |
| Multiplayer / servers | 886 | 38.7% | 17.6% | 43.7% |
| Bugs | 845 | 13.3% | 24.9% | 61.9% |
| Performance | 840 | 30.2% | 29.3% | 40.5% |
| Graphics | 783 | 62.6% | 23.1% | 14.3% |
| Price / value | 641 | 40.4% | 26.2% | 33.4% |
| Content / length | 611 | 46.0% | 33.1% | 20.9% |

Players mostly praise gameplay, story and graphics, and mostly complain about bugs, servers and performance.

**Per-topic sentiment changes the picture.** 27.3% of topic tags got a different label than their whole review.
- **485 complaints sit inside 397 Recommended reviews,** for example "Capcom's absolute garbage optimization at launch forced me to buy a whole new PC".
- **205 pieces of praise sit inside Not recommended reviews.**

**How accurate is it?** There's no answer key for topics, so I read 50 random praise and complaint tags. That is my judgement, not a measurement against labels.

| Result | Count | Examples |
|---|---|---|
| Clearly right | 38 | |
| Wrong topic | 3 | in-game money ("my city is $2 million in debt") as price; "graphic settings" as graphics; a player's "performance" in matchmaking |
| Wrong or unsupported sentiment | 4 | "Some bugs remain" as praise; "Multiplayer – 2/10" as praise; a template heading and "the movement" with no opinion at all |
| Debatable | 5 | |

**Known weaknesses, seen in real data.**
- **Keywords can't tell meanings apart.** Hollow Knight's characters are insects: its "bugs" topic has 37 mentions, and 20 of them read as praise ("bug kills bug, peak").
- **The classifier was trained to predict a whole review's vote, not the tone of a fragment.**
  - The word "bug" itself has a positive weight (+0.38), probably learned from Hollow Knight's happy reviews. So "Game breaking bug" scored +0.31, which counts as praise.
  - "no bugs" scores negative, because "no" usually appears in complaints.
  - Words that carry the feeling themselves work well: "crashes" has a weight of −4.23.
- **Number ratings mean nothing to it.** "Multiplayer: 2/10" isn't read as a low score.

**Cost.**
- **Memory:** the API used 119.1 MiB after scoring with the model loaded, the same as before topics (120.3 MiB).
- **Speed:** the topic endpoint answered in 21–56 ms. Re-scoring and topic-tagging all 17,552 reviews from the command line took 6.6 s.

### Sentiment around updates

**Why fetching was needed.** For most games the newest 1,000 reviews covered only 7–37 days. Of all updates found, only 4 across 2 games had stored reviews covering the 2 weeks on both sides.

**The update rule on real news, last 12 months.** After tightening, it finds:
- Patch posts for Black Myth: Wukong, Hollow Knight, Portal 2, Starfield, Baldur's Gate 3 and Elden Ring.
- Changelogs for PAYDAY 3 and Cities: Skylines II.
- Version posts for Dead by Daylight and Monster Hunter Wilds.
- Season launches for Overwatch.

Known misses: Rust's monthly updates, whose titles are single words like "LIVESTOCK", and posts with no update wording at all.

**Black Myth: Wukong**, 2 updates:

| Update | Reviews before / after | Average score before → after | Recommended before → after |
|---|---|---|---|
| Jan 14, 2026 | 294 / 234 | +0.470 → +0.491 (+0.021) | 89.1% → 90.2% |
| Oct 16, 2025 | 292 / 311 | +0.523 → +0.538 (+0.015) | 91.1% → 92.9% |

**PAYDAY 3**, 10 updates.
- **Biggest rises:** Update 3.9 (+0.175, Recommended 74.7% → 87.7%), 3.5 (+0.124) and 3.2 (+0.119).
- **Biggest drops:** Update 3.4 (−0.165), 2.5 (−0.081) and 3.3 (−0.044).
- **The score and the votes disagree for 4 of the 10 updates.** After Update 3.4 the average score fell by 0.165 while Recommended rose from 60.4% to 66.2%, on 48 and 68 reviews. Small samples and a vote-predicting model make these numbers noisy, which is one more reason not to read cause into them.

**Overwatch** (3 of its 5 updates fetched): shifts of +0.007, −0.002 and −0.060, on about 1,300–1,400 reviews per side.
- **68 of its 84 fetched days hit the 100-review cap,** so its windows are samples.
- PAYDAY 3 (at most 32 reviews a day) and Black Myth: Wukong (at most 40) never hit it.

**Timing.**
- One update took 33–36 s, or 18.9 s when half its days were already fetched.
- Reading the news alone took 0.1 s.
- Steam rate limited us once, after about 125 requests in 2.5 minutes. It lifted within 91 s of probing.

## 6. Interview questions

**Walk me through the architecture.**
A FastAPI service and PostgreSQL, run together with Docker Compose. `POST /games/{id}/fetch` pulls reviews from Steam's API page by page, saves them without duplicates, labels each one with a TF-IDF + logistic regression classifier trained on Steam reviews, and tags the topics it mentions. `GET` endpoints serve a summary, a weekly trend, a topic breakdown, before/after numbers around game updates, and filtered, paginated reviews to a React frontend. A second `POST` reads a game's Steam news for updates and fetches the reviews around them. The fetching and scoring logic lives in one shared package that both the API and the command-line scripts use.

**What happens if you fetch the same game twice?**
Nothing bad. Each review has Steam's unique ID as the primary key, and inserts use `ON CONFLICT DO NOTHING`, so known reviews are skipped. The response's `new` count shows how many were actually added. A test covers this: the second fetch returns `new: 0`.

**How do you handle Steam failing or rate limiting you?**
- **Network errors, 429s and 5xx errors** are retried up to 3 times with exponential backoff. If Steam sends `Retry-After`, I wait that long instead, capped at 60 seconds.
- **Other errors, like a 404,** fail at once, because retrying can't fix them.
- **If it still fails,** the API returns `502`, so the client knows the problem is upstream. Pages already saved are kept and scored.
- **I pause 1 second between pages**, so I'm unlikely to be rate limited in the first place.

**Why did you start with VADER, and why did you replace it?**
- **Why start with it:** it needs no training data, is very fast, and every score can be explained word by word. That made it a good first model and a benchmark.
- **Why replace it:** its general-purpose word list doesn't fit games. "insane", "fights", "combat" and "sick" all count as negative, so it missed half the complaints on unseen games.
- **What replaced it:** a TF-IDF + logistic regression classifier trained on 16,500 Steam reviews, using each player's own vote as the label.
- **The result,** on 4 games it never saw: positive and negative labels are right 90.9% of the time (VADER 82.6%), and it catches 63.9% of Not recommended reviews (VADER 49.3%).
- **The tradeoff:** it predicts whether someone recommends the game, not the text's tone, and it has to be retrained as data grows.

**Your dashboard says agreement is 79.8%, but you quote 68.8%. Which is right?**
Both, for different questions.
- **79.8%** is measured on the reviews the model trained on, so it's optimistic: the model has partly memorized them.
- **68.8%** comes from 4 games held out of training. That's the honest estimate for a game someone fetches tomorrow.

I'd always quote the held-out number.

**How do you know whether your sentiment model is any good?**
I compare its label to the player's own thumbs up/down, which is free labeled data. Raw agreement is misleading because most reviews are positive, so I always show the majority-class baseline next to it. I also break agreement down by class, because Not recommended reviews are the ones a dashboard most needs to surface. VADER caught only 43.1% of Cities: Skylines II's as negative, which is what led to replacing it.

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

**Why does the trend only cover a few weeks for some games?**
Each fetch starts from the newest review, and 1,000 reviews reach back only 7–37 days for most of these games. Fetching the reviews around updates adds older weeks, with gaps in between. A continuous longer trend needs a bigger fetch, or remembering the cursor where the last fetch stopped so each fetch continues further back.

**Why didn't you download Steam's full list of games?**
I tested both options with real calls before choosing.
- **The classic full-list endpoint no longer exists.** It returns 404 "Method not found".
- **Its replacement needs a Steam Web API key** (a secret to manage), a table, and a job to keep it current.
- **It doesn't give cover images,** and the old image URL pattern 404s for newer games.

The store search needed none of that and ranks popular games first. Its weaknesses, typos and the risk of rate limits, I handled with a typo fallback, a cache and debouncing.

**How does the search box avoid hammering Steam?**
Three layers:
1. **Debouncing.** The browser waits for a 300 ms pause in typing, so typing "hollow knight" sent one request instead of 13.
2. **Cancelling.** Typing again cancels a search that's already running.
3. **Caching.** The backend remembers answers for an hour, so a repeat search took 0.006 s instead of 0.29 s and never reached Steam.

On top of that, search retries less and gives up sooner than fetching does, and it respects `Retry-After` when Steam rate limits.

**Why route search through your backend instead of calling Steam from the browser?**
Steam's store search sends no CORS header, so the browser couldn't read its responses anyway. Beyond that, the backend is the one place to:
- cache and retry
- handle rate limits
- adapt if Steam changes its undocumented format, without the frontend noticing

**How does the frontend handle errors?**
Every failure becomes a message that says what to do. The API client (`api.ts`) maps each case to plain language:
- Can't connect: "is the API running? Start it with `docker compose up -d`".
- `404`: the game isn't stored, so the page offers to fetch it.
- `502`: Steam is down, try again later.
- `503`: the database is down.

Each message has a "Try again" button. Bad input is caught before any request. I tested each case against the real stack by stopping the API container and the database container while the page was open.

**How did you make sure it works on phones?**
The CSS is mobile-first: one column by default, with wider layouts added at 640px and 900px. Charts use Recharts' `ResponsiveContainer` to fill whatever width they get. I checked it in a browser at 375px, 768px and 1280px, including a script confirming the page is never wider than the screen. That check caught the sentiment filter chips running off a phone screen; they now wrap.

**Why a pie chart if they're often criticized?**
The requirement was a pie, and with only three slices showing part of a whole it reads fine. To make it accessible:
- The colors follow the scale's order (blue = positive, gray = neutral, red = negative) and were validated for colorblind separation.
- 2px gaps separate the slices.
- A legend with exact percentages sits right next to it, so nobody has to judge angles.

**How did you decide which sentiment model to use?**
I measured instead of guessing.
1. **I ruled out a bug.** All 6,500 labels matched their scores, and re-scoring reproduced them.
2. **I compared three approaches** on 4,000 reviews from four games the trained model never saw, using each player's thumbs up/down as the answer key.
3. **The headline accuracy barely separated them** (83.3%, 83.8%, 85.7% against an 81.0% baseline), because most reviews are positive.
4. **What separated them was how many complaints each caught:** VADER 50.5%, the transformer 84.6%, TF-IDF 77.5%.
5. **Then I weighed fit:** the transformer peaked at 1.7–2.5 GB against a 512 MB free tier, while TF-IDF peaked at about 155 MB and ran hundreds of times faster (about 690× in the latest run).

**Why test on whole games instead of a random split?**
A classifier trained on our reviews can memorize game-specific words: character names, "Todd", a game's title. A random split would put the same games in training and test and flatter it. Holding out whole games measures what the app actually does, which is score reviews for games it has never seen.

**Why not just use the transformer, since it understands context best?**
- It needed **1.7–2.5 GB** at peak on my Mac across three runs, 3–5× the free tier's 512 MB, before counting the rest of the API.
- It scored **36–42 reviews/s** using my Mac's whole CPU. The free tier has 0.1 CPU.
- To use it, I'd score reviews outside the API, use a compressed version (and re-test it), or pay for a bigger server.
- It also misreads gamer sarcasm like "10/10 would get scammed again". "Most accurate in general" isn't automatically "best for this data".

**How do you keep secrets out of the code?**
Credentials live in `.env`, which is git-ignored, with `.env.example` as a template. Docker Compose reads the same file. All SQL uses parameterized queries, so user input is never pasted into SQL.

**How does the topic breakdown work?**
1. **Find topics.** Each topic has a list of keyword patterns, matched as whole words. Each review is cut into parts at sentence ends, line breaks, list items, and words like "but".
2. **Score each topic.** For each topic, the parts that mention it are joined into an excerpt. Only that excerpt is scored with the sentiment classifier.
3. **Store.** The tags go into a `review_topics` table while the review is scored.
4. **Read.** One endpoint returns per-topic counts of praise and complaints, plus the most helpful example excerpts. The dashboard shows it as a chart with complaints to the left and praise to the right.

**Why keywords instead of machine learning?**
- **They were the right first version:** instant, no extra memory on a 512 MB server, free, and every tag can be explained.
- **The cost is recall:** they only find the words I listed, so "my GPU is crying" isn't a performance complaint.
- **Why not the smarter options:**
  - a trained classifier needs hundreds of hand-labeled reviews per topic, and I have none
  - a zero-shot transformer needs the 1.7–2.5 GB I'd already measured
  - an LLM costs money per review
- **How I'd upgrade:** hand-label a few hundred reviews, measure the keywords' precision and recall against them, then train a classifier and compare it on the same labels.

**How do you get sentiment for each topic, not just each review?**
- **Only the parts that mention a topic are scored for it.** In "Great game, but it runs terribly", performance is a complaint even though the review is positive.
- **Real effect:** 27.3% of topic tags got a different label than their review, and 397 Recommended reviews contained a complaint that a review-level label would have hidden.

**How accurate is the topic breakdown?**
I can't give an accuracy number, because there's no answer key for topics. What I can say honestly:
- **Coverage:** 27.2% of reviews get a tag, 62.2% of those with 20+ words. Most untagged ones are very short.
- **A spot check:** I read 50 random tags; 38 were clearly right, 7 wrong, 5 debatable. That's my judgement on a small sample.
- **Known failures:**
  - Hollow Knight's insect "bugs".
  - "Game breaking bug" scored as praise, because the classifier learned "bug" as a positive word from that same game.
  - Rating text like "2/10".

The next step would be a few hundred hand-labeled excerpts to measure it properly.

**Why store topic tags instead of computing them on each request?**
- **It's cheap to read:** the endpoint answers in 21–56 ms with a SQL query, which matters on a 0.1-CPU server.
- **The cost:** changing a keyword means re-running the scoring script with `--rescore`. That took 6.6 s for all 17,552 reviews.

**How does the update comparison work?**
1. **Find updates.** Read the game's official Steam news and decide which posts are updates, using Steam's patch-notes tag or the title.
2. **Group them.** Updates less than 2 weeks apart are merged into one.
3. **Fetch reviews.** For each of the 10 most recent finished updates, fetch the reviews from the 14 days before and the 14 days after, one day at a time, up to 100 per day.
4. **Compare.** Compare the average model score, the share of Recommended votes, and the review counts, then rank the biggest rises and drops among updates with at least 30 reviews on each side.

**How do you avoid claiming an update caused a change?**
- **Wording:** the feature only reports before and after numbers. The page never says "impact" or "caused", and it explains that sales, events, seasons and new players arrive at the same time.
- **The data backs that up:** for PAYDAY 3, the model's score and the players' votes moved in opposite directions for 4 of 10 updates.
- **Showing a cause would need a comparison group,** for example similar games that didn't update in the same weeks.

**How did you get reviews from months ago when Steam's API only goes newest-first?**
- **The documented way doesn't scale:** reaching an update 6 months back means paging through every newer review first, which is thousands of requests for a busy game.
- **I found that the review API accepts a date range,** the same one the Steam store's own review filter uses. I tested it on real games before relying on it: every returned review was from the requested day.
- **Because it's undocumented,** the code checks each answer and treats "no reviews from that day" as an error rather than as data.

**What went wrong when you tried it on real data?**
Steam rate limited us. After about 125 requests in 2.5 minutes it answered 429 three times, with no `Retry-After` header.
- **Measuring first:** I tried one request every 30 seconds, and it lifted within 91 s.
- **The fix:** the API now answers `429 Retry-After: 60` and keeps the days already fetched. The page waits a minute and continues, up to 5 times.

I didn't slow down every request, because I don't know Steam's actual limit and didn't want to guess.

**What are the feature's limits?**
- **Update detection is a title heuristic.** It misses Rust's one-word update titles.
- **Busy days are sampled.** For Overwatch, 68 of 84 days had more than 100 reviews, so only 100 were fetched.
- **Many shifts are small** compared to how much the numbers move from week to week.
- **The extra reviews change the other charts,** since they become part of the game's stored reviews.
- **Leaving the page stops the loop,** but a request already running on the server finishes and saves its reviews.
