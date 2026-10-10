"""
REST API for the Steam review sentiment dashboard.

Run it (from the project root):
    uvicorn --app-dir backend app.main:app --reload
Interactive docs: http://localhost:8000/docs
"""

import os
from datetime import date, datetime
from typing import Annotated, Literal

import psycopg
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from pydantic import BaseModel

from app import db, search, steam, topics, updates
from app.steam import SteamError, SteamRateLimited, fetch_reviews, to_row

MAX_FETCH = 5000  # the fetch request waits until done, so cap how long that can take
RATE_LIMIT_WAIT = 60  # seconds to suggest waiting when Steam is limiting our requests

load_dotenv()  # reads the project's .env when running locally; in Docker, compose sets these
DATABASE_URL = db.database_url()  # read once at startup, so a missing setting fails fast
# Frontend addresses allowed to call the API from a browser (Vite's dev server by default).
CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")]

app = FastAPI(title="Steam Review Sentiment API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# lt=2**31: the app_id column is a PostgreSQL INTEGER, so bigger numbers would crash the query
AppId = Annotated[int, Path(gt=0, lt=2**31, description="Steam app ID, e.g. 620 for Portal 2")]
Sentiment = Literal["positive", "neutral", "negative"]


def get_conn():
    """One database connection per request, closed when the request finishes."""
    with psycopg.connect(DATABASE_URL) as conn:
        yield conn


@app.exception_handler(psycopg.OperationalError)
def database_unavailable(request: Request, error: psycopg.OperationalError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "Database is unavailable. Is it running?"})


def no_reviews(app_id: int) -> HTTPException:
    return HTTPException(404, f"No reviews stored for app {app_id}. POST /games/{app_id}/fetch first.")


HAS_REVIEWS_SQL = "SELECT EXISTS (SELECT 1 FROM reviews WHERE app_id = %s AND sentiment_label IS NOT NULL)"


def require_reviews(conn: psycopg.Connection, app_id: int) -> None:
    if not conn.execute(HAS_REVIEWS_SQL, (app_id,)).fetchone()[0]:
        raise no_reviews(app_id)


def pct(part: int, whole: int) -> float:
    return round(100 * part / whole, 1)


# ---------- GET /search ----------

class SearchResult(BaseModel):
    app_id: int
    name: str
    image_url: str | None  # small cover image on Steam's servers


class SearchResponse(BaseModel):
    query: str          # what was searched for, cleaned up (lowercase, single spaces)
    matched_query: str  # what produced the results; shorter than `query` when a typo was trimmed
    results: list[SearchResult]


@app.get("/search", response_model=SearchResponse)
def search_games(q: Annotated[str, Query(max_length=100, description="Part of a game's name, e.g. hollow kni")]):
    """Find games by name, most relevant first (at most 10). Asks Steam's store search
    through our backend, with a 1-hour cache and a fallback for typos."""
    query = search.normalize(q)
    if len(query) < 2:
        raise HTTPException(422, "Type at least 2 characters to search.")
    try:
        matched_query, results = search.search_games(query)
    except SteamError as error:
        raise HTTPException(502, f"Steam search error: {error}") from error
    return SearchResponse(query=query, matched_query=matched_query, results=results)


# ---------- POST /games/{app_id}/fetch ----------

class FetchResult(BaseModel):
    app_id: int
    fetched: int  # reviews received from Steam
    new: int      # of those, reviews that weren't already stored
    scored: int   # reviews given a sentiment score by this request


@app.post("/games/{app_id}/fetch", response_model=FetchResult)
def fetch_game(
    app_id: AppId,
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
    max_reviews: Annotated[int, Query(ge=1, le=MAX_FETCH)] = 1000,
):
    """Fetch the newest English reviews from Steam, save the new ones and score them.
    The request waits until everything is done (at least 1 second per 100 reviews)."""
    fetched = new = 0
    try:
        for page in fetch_reviews(app_id, max_reviews):
            rows = [to_row(app_id, review) for review in page]
            new += db.save_reviews(conn, rows)
            fetched += len(rows)
    except SteamError as error:
        db.score_reviews(conn, app_id=app_id)  # pages saved before the failure still get scored
        raise HTTPException(502, f"Steam API error: {error}") from error

    if fetched == 0:
        # Steam answers the same way (success=1, no reviews) for app IDs that don't exist
        # and for real apps with no reviews, so we can't tell which one this is.
        raise HTTPException(404, f"Steam returned no English reviews for app {app_id}. "
                                 "The app may not exist, or it has no reviews yet.")

    scored = db.score_reviews(conn, app_id=app_id)
    return FetchResult(app_id=app_id, fetched=fetched, new=new, scored=scored)


# ---------- GET /games/{app_id}/summary ----------

class Summary(BaseModel):
    app_id: int
    total_reviews: int
    positive_pct: float
    neutral_pct: float
    negative_pct: float
    agreement_pct: float  # the model's label matches the player's vote; neutral counts as a miss
    baseline_pct: float   # what always guessing the more common vote would score


SUMMARY_SQL = """
    SELECT count(*),
           count(*) FILTER (WHERE sentiment_label = 'positive'),
           count(*) FILTER (WHERE sentiment_label = 'neutral'),
           count(*) FILTER (WHERE sentiment_label = 'negative'),
           count(*) FILTER (WHERE voted_up),
           -- agreement: positive label = Recommended, negative label = Not recommended
           count(*) FILTER (WHERE (voted_up AND sentiment_label = 'positive')
                               OR (NOT voted_up AND sentiment_label = 'negative'))
    FROM reviews
    WHERE app_id = %s AND sentiment_label IS NOT NULL
"""


@app.get("/games/{app_id}/summary", response_model=Summary)
def game_summary(app_id: AppId, conn: Annotated[psycopg.Connection, Depends(get_conn)]):
    """Review count, sentiment split, and how often the model's labels match the players' own votes."""
    total, positive, neutral, negative, recommended, agree = conn.execute(SUMMARY_SQL, (app_id,)).fetchone()
    if total == 0:
        raise no_reviews(app_id)
    return Summary(
        app_id=app_id,
        total_reviews=total,
        positive_pct=pct(positive, total),
        neutral_pct=pct(neutral, total),
        negative_pct=pct(negative, total),
        agreement_pct=pct(agree, total),
        baseline_pct=pct(max(recommended, total - recommended), total),
    )


# ---------- GET /games/{app_id}/trend ----------

class TrendWeek(BaseModel):
    week: str            # the Monday the week starts on, e.g. "2026-09-21"
    avg_compound: float  # average model score: -1 (likely Not recommended) to +1 (likely Recommended)
    review_count: int    # so a week with a handful of reviews isn't read like one with hundreds


class Trend(BaseModel):
    app_id: int
    weeks: list[TrendWeek]  # only weeks with reviews; there can be gaps


# Weeks (Monday to Sunday) are in UTC so the result doesn't depend on the database server's time zone.
TREND_SQL = """
    SELECT to_char(date_trunc('week', created_at AT TIME ZONE 'UTC'), 'YYYY-MM-DD'),
           avg(sentiment_compound),
           count(*)
    FROM reviews
    WHERE app_id = %s AND sentiment_label IS NOT NULL
    GROUP BY 1
    ORDER BY 1
"""


@app.get("/games/{app_id}/trend", response_model=Trend)
def game_trend(app_id: AppId, conn: Annotated[psycopg.Connection, Depends(get_conn)]):
    """Average sentiment for each week, by the date reviews were posted."""
    rows = conn.execute(TREND_SQL, (app_id,)).fetchall()
    if not rows:
        raise no_reviews(app_id)
    weeks = [TrendWeek(week=week, avg_compound=round(avg, 3), review_count=count) for week, avg, count in rows]
    return Trend(app_id=app_id, weeks=weeks)


# ---------- GET /games/{app_id}/topics ----------

EXAMPLES_PER_SIDE = 3


class TopicExample(BaseModel):
    recommendation_id: int
    excerpt: str            # the part of the review that mentions the topic
    sentiment_score: float  # the model's score for the excerpt alone, -1 to +1
    voted_up: bool
    helpful_votes: int


class TopicSummary(BaseModel):
    topic: str     # e.g. "performance"; the full list is topics.TOPICS
    mentions: int  # reviews that mention the topic
    positive: int  # of those, how many the model reads as praise / isn't sure about / complaints
    neutral: int
    negative: int
    praise: list[TopicExample]      # up to 3 positive excerpts, most helpful first
    complaints: list[TopicExample]  # up to 3 negative ones


class Topics(BaseModel):
    app_id: int
    total_reviews: int           # every scored review, including those that mention no topic
    topics: list[TopicSummary]   # every topic, most mentioned first


TOTAL_SCORED_SQL = "SELECT count(*) FROM reviews WHERE app_id = %s AND sentiment_label IS NOT NULL"

TOPIC_COUNTS_SQL = """
    SELECT t.topic,
           count(*),
           count(*) FILTER (WHERE t.sentiment_label = 'positive'),
           count(*) FILTER (WHERE t.sentiment_label = 'neutral'),
           count(*) FILTER (WHERE t.sentiment_label = 'negative')
    FROM review_topics t JOIN reviews r USING (recommendation_id)
    WHERE r.app_id = %s
    GROUP BY t.topic
"""

# The top few praise and complaint excerpts for each topic: the ones most players marked
# helpful, then the ones the model is most sure about.
TOPIC_EXAMPLES_SQL = """
    SELECT topic, sentiment_label, recommendation_id, excerpt, sentiment_score, voted_up, helpful_votes
    FROM (
        SELECT t.topic, t.sentiment_label, t.recommendation_id, t.excerpt, t.sentiment_score,
               r.voted_up, r.helpful_votes,
               row_number() OVER (
                   PARTITION BY t.topic, t.sentiment_label
                   ORDER BY r.helpful_votes DESC, abs(t.sentiment_score) DESC, t.recommendation_id
               ) AS rank
        FROM review_topics t JOIN reviews r USING (recommendation_id)
        WHERE r.app_id = %(app_id)s AND t.sentiment_label <> 'neutral'
    ) ranked
    WHERE rank <= %(per_side)s
    ORDER BY rank
"""


@app.get("/games/{app_id}/topics", response_model=Topics)
def game_topics(app_id: AppId, conn: Annotated[psycopg.Connection, Depends(get_conn)]):
    """How many reviews mention each topic (performance, bugs, price/value, ...), how many of
    those praise or complain about it, and example excerpts. Topics are found by keywords."""
    total = conn.execute(TOTAL_SCORED_SQL, (app_id,)).fetchone()[0]
    if total == 0:
        raise no_reviews(app_id)
    counts = {topic: rest for topic, *rest in conn.execute(TOPIC_COUNTS_SQL, (app_id,))}
    examples: dict[tuple[str, str], list[TopicExample]] = {}
    with conn.cursor(row_factory=dict_row) as cur:
        for row in cur.execute(TOPIC_EXAMPLES_SQL, {"app_id": app_id, "per_side": EXAMPLES_PER_SIDE}):
            key = (row.pop("topic"), row.pop("sentiment_label"))
            examples.setdefault(key, []).append(TopicExample(**row))

    summaries = []
    for topic in topics.TOPICS:
        mentions, positive, neutral, negative = counts.get(topic, (0, 0, 0, 0))
        summaries.append(TopicSummary(
            topic=topic, mentions=mentions, positive=positive, neutral=neutral, negative=negative,
            praise=examples.get((topic, "positive"), []),
            complaints=examples.get((topic, "negative"), []),
        ))
    summaries.sort(key=lambda s: s.mentions, reverse=True)  # a stable sort, so ties keep the topic order
    return Topics(app_id=app_id, total_reviews=total, topics=summaries)


# ---------- GET /games/{app_id}/updates and POST /games/{app_id}/updates/fetch ----------

class WindowStats(BaseModel):
    reviews: int
    avg_score: float | None        # average model score, -1 to +1
    recommended_pct: float | None  # share of these reviewers who voted Recommended


class UpdatePost(BaseModel):
    gid: str  # Steam's ID for the news post
    title: str
    url: str
    posted_at: datetime


class UpdateComparison(BaseModel):
    day: date                 # the update's day (UTC): compared are the 14 days before it and the 14 after
    posts: list[UpdatePost]   # the update, plus further update posts less than 14 days after it
    status: Literal["ready", "too_few_reviews", "needs_reviews", "too_recent"]
    before: WindowStats | None
    after: WindowStats | None
    shift: float | None       # after minus before, in average score; a difference, not an effect


class Updates(BaseModel):
    app_id: int
    window_days: int
    min_reviews: int                       # per side, to be ranked among the biggest shifts
    updates: list[UpdateComparison]        # last 12 months, newest first
    biggest_rises: list[UpdateComparison]  # up to 3, largest first
    biggest_drops: list[UpdateComparison]


class UpdateFetchResult(BaseModel):
    app_id: int
    updates_found: int         # update posts in the game's official news from the last 12 months
    fetched_day: date | None   # the update whose reviews this request fetched, if any
    new_reviews: int
    remaining: int             # updates still waiting for their reviews; call again for the next one


@app.get("/games/{app_id}/updates", response_model=Updates)
def game_updates(app_id: AppId, conn: Annotated[psycopg.Connection, Depends(get_conn)]):
    """Average sentiment in the 2 weeks before vs. the 2 weeks after each update from the last
    12 months, and the biggest rises and drops. Before/after only: it doesn't show that an update
    caused a change. Uses the updates and reviews already stored; POST .../updates/fetch gets them."""
    require_reviews(conn, app_id)
    results = updates.compare(conn, app_id, updates.today())
    rises, drops = updates.biggest_shifts(results)
    return Updates(app_id=app_id, window_days=updates.WINDOW_DAYS, min_reviews=updates.MIN_REVIEWS,
                   updates=results, biggest_rises=rises, biggest_drops=drops)


@app.post("/games/{app_id}/updates/fetch", response_model=UpdateFetchResult)
def fetch_update_reviews(app_id: AppId, conn: Annotated[psycopg.Connection, Depends(get_conn)]):
    """Read the game's official Steam news for updates, then fetch the reviews around the newest
    update that doesn't have them yet: up to 100 per day for the 14 days before and after (28
    requests, about 30–40 seconds). Call again until `remaining` is 0."""
    require_reviews(conn, app_id)
    today = updates.today()
    try:
        posts = [post for post in steam.fetch_news(app_id) if updates.is_update(post)]
    except SteamError as error:
        raise HTTPException(502, f"Steam news error: {error}") from error
    updates.save_posts(conn, app_id, posts)

    waiting = [r for r in updates.compare(conn, app_id, today) if r["status"] == "needs_reviews"]
    if not waiting:
        return UpdateFetchResult(app_id=app_id, updates_found=len(updates.in_lookback(posts, today)),
                                 fetched_day=None, new_reviews=0, remaining=0)
    day = waiting[0]["day"]  # newest first
    try:
        new = updates.fetch_window_reviews(conn, app_id, updates.missing_days(conn, app_id, day))
    except SteamRateLimited as error:
        db.score_reviews(conn, app_id=app_id)  # days fetched before the failure are kept and scored
        raise HTTPException(429, "Steam is limiting requests right now. The reviews fetched so far are saved; "
                                 "try again in a minute to continue.",
                            headers={"Retry-After": str(RATE_LIMIT_WAIT)}) from error
    except SteamError as error:
        db.score_reviews(conn, app_id=app_id)
        raise HTTPException(502, f"Steam API error: {error}") from error
    db.score_reviews(conn, app_id=app_id)
    return UpdateFetchResult(app_id=app_id, updates_found=len(updates.in_lookback(posts, today)),
                             fetched_day=day, new_reviews=new, remaining=len(waiting) - 1)


# ---------- GET /games/{app_id}/reviews ----------

class Review(BaseModel):
    recommendation_id: int
    review_text: str
    voted_up: bool
    sentiment_label: Sentiment
    sentiment_compound: float
    playtime_at_review_minutes: int | None
    helpful_votes: int
    created_at: datetime


class ReviewPage(BaseModel):
    app_id: int
    page: int
    page_size: int
    total: int  # reviews matching the filter, across all pages
    items: list[Review]


REVIEWS_FILTER = """
    FROM reviews
    WHERE app_id = %(app_id)s AND sentiment_label IS NOT NULL
      AND (%(sentiment)s::text IS NULL OR sentiment_label = %(sentiment)s)
"""
COUNT_REVIEWS_SQL = "SELECT count(*)" + REVIEWS_FILTER
PAGE_REVIEWS_SQL = """
    SELECT recommendation_id, review_text, voted_up, sentiment_label, sentiment_compound,
           playtime_at_review_minutes, helpful_votes, created_at
""" + REVIEWS_FILTER + """
    ORDER BY created_at DESC, recommendation_id DESC  -- the id breaks ties, so pages never overlap
    LIMIT %(limit)s OFFSET %(offset)s
"""


@app.get("/games/{app_id}/reviews", response_model=ReviewPage)
def game_reviews(
    app_id: AppId,
    conn: Annotated[psycopg.Connection, Depends(get_conn)],
    sentiment: Sentiment | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    """Reviews for a game, newest first, optionally only one sentiment."""
    require_reviews(conn, app_id)
    params = {"app_id": app_id, "sentiment": sentiment, "limit": page_size, "offset": (page - 1) * page_size}
    total = conn.execute(COUNT_REVIEWS_SQL, params).fetchone()[0]
    with conn.cursor(row_factory=dict_row) as cur:
        items = [Review(**row) for row in cur.execute(PAGE_REVIEWS_SQL, params)]
    return ReviewPage(app_id=app_id, page=page, page_size=page_size, total=total, items=items)
