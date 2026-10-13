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

from app import db, gaps, offtopic, playtime, search, shelf, steam, topics, updates
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


# ---------- GET /games ----------

class StoredGame(BaseModel):
    app_id: int
    name: str | None   # None until Steam's store details could be looked up
    image_url: str     # Steam's wide header image
    total_reviews: int
    negative_pct: float
    neutral_pct: float
    positive_pct: float


class StoredGames(BaseModel):
    total_reviews: int        # across every stored game
    games: list[StoredGame]   # most reviews first


@app.get("/games", response_model=StoredGames)
def list_games(conn: Annotated[psycopg.Connection, Depends(get_conn)]):
    """Every game with scored reviews, for the front page. Names and covers come from Steam's store
    the first time a game is listed (about a third of a second each), then from the database."""
    games = shelf.stored_games(conn)
    return StoredGames(total_reviews=sum(g["total_reviews"] for g in games), games=games)


# ---------- GET /games/{app_id}/details ----------

class GameDetails(BaseModel):
    app_id: int
    name: str
    image_url: str  # Steam's wide header image


@app.get("/games/{app_id}/details", response_model=GameDetails)
def get_game_details(app_id: AppId, conn: Annotated[psycopg.Connection, Depends(get_conn)]):
    """A game's name and cover, for a dashboard opened from its web address. Works for any game on
    Steam, stored or not; looked up from Steam's store once, then kept in the database."""
    try:
        details = shelf.game_details(conn, app_id)
    except SteamError as error:
        raise HTTPException(502, f"Steam store error: {error}") from error
    if details is None:
        raise HTTPException(404, f"Steam has no store page for app {app_id}.")
    return details


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


# ---------- GET /games/{app_id}/trend and POST /games/{app_id}/trend/fill ----------

class TrendMonth(BaseModel):
    month: str           # the first day of the month, e.g. "2026-09-01"
    avg_compound: float  # average model score, -1 (likely Not recommended) to +1 (likely Recommended),
                         # of the month's weekly averages: each week counts the same however many reviews it has
    review_count: int    # so a month with a handful of reviews isn't read like one with hundreds
    weeks: int           # weeks in the month that have reviews


class Trend(BaseModel):
    app_id: int
    months: list[TrendMonth]  # only months with reviews; there can be gaps
    weeks_to_fill: int        # weeks of the past year under 30 reviews that POST .../trend/fill hasn't asked Steam about yet


class GapFillResult(BaseModel):
    app_id: int
    filled_weeks: int  # weeks this request asked Steam about
    new_reviews: int
    remaining: int     # weeks still to fill; call again for the next ones


# Average per week first (Monday to Sunday, in UTC so the result doesn't depend on the database's
# time zone), then per month. Some weeks were fetched in full (the newest reviews, the days around
# updates) and others are samples of 100 (trend/fill), so pooling reviews would let the full weeks
# outweigh the rest; averaging the weekly averages counts each week once. A week belongs to the
# month its Thursday is in, the ISO rule, so it's never split between two months.
TREND_SQL = """
    WITH weekly AS (
        SELECT date_trunc('week', created_at AT TIME ZONE 'UTC') AS week,
               avg(sentiment_compound) AS avg_score,
               count(*) AS reviews
        FROM reviews
        WHERE app_id = %s AND sentiment_label IS NOT NULL
        GROUP BY 1
    )
    SELECT to_char(date_trunc('month', week + interval '3 days'), 'YYYY-MM-DD'),
           avg(avg_score),
           sum(reviews),
           count(*)
    FROM weekly
    GROUP BY 1
    ORDER BY 1
"""


@app.get("/games/{app_id}/trend", response_model=Trend)
def game_trend(app_id: AppId, conn: Annotated[psycopg.Connection, Depends(get_conn)]):
    """Average sentiment for each month, by the date reviews were posted."""
    rows = conn.execute(TREND_SQL, (app_id,)).fetchall()
    if not rows:
        raise no_reviews(app_id)
    months = [TrendMonth(month=month, avg_compound=round(avg, 3), review_count=count, weeks=weeks)
              for month, avg, count, weeks in rows]
    return Trend(app_id=app_id, months=months, weeks_to_fill=len(gaps.weeks_to_fill(conn, app_id, updates.today())))


@app.post("/games/{app_id}/trend/fill", response_model=GapFillResult)
def fill_trend_gaps(app_id: AppId, conn: Annotated[psycopg.Connection, Depends(get_conn)]):
    """Fill the trend chart's past year: for up to 10 past weeks with fewer than 30 stored reviews (newest
    first), fetch the newest 100 reviews of each week (one request per week, about 15 seconds in all).
    A sample, not the whole week. Call again until `remaining` is 0."""
    require_reviews(conn, app_id)
    waiting = gaps.weeks_to_fill(conn, app_id, updates.today())
    batch = waiting[:gaps.WEEKS_PER_REQUEST]
    try:
        new = gaps.fill_weeks(conn, app_id, batch)
    except SteamRateLimited as error:
        db.score_reviews(conn, app_id=app_id)  # weeks filled before the failure are kept and scored
        raise HTTPException(429, "Steam is limiting requests right now. The reviews fetched so far are saved; "
                                 "try again in a minute to continue.",
                            headers={"Retry-After": str(RATE_LIMIT_WAIT)}) from error
    except SteamError as error:
        db.score_reviews(conn, app_id=app_id)
        raise HTTPException(502, f"Steam API error: {error}") from error
    db.score_reviews(conn, app_id=app_id)
    return GapFillResult(app_id=app_id, filled_weeks=len(batch), new_reviews=new,
                         remaining=len(waiting) - len(batch))


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


# ---------- GET /games/{app_id}/playtime ----------

class PlaytimeGroupStats(BaseModel):
    group: playtime.PlaytimeGroup
    reviews: int
    recommended: int               # how many of them voted Recommended
    recommended_pct: float | None  # None when the group has fewer than min_reviews: too few to compare
    avg_score: float | None        # average model score, -1 to +1; None likewise


class Playtime(BaseModel):
    app_id: int
    total_reviews: int
    min_reviews: int                  # a group needs this many for its percentages
    unknown_playtime: int             # reviews Steam sent without a playtime; they're in no group
    groups: list[PlaytimeGroupStats]  # always all four, shortest playtime first


PLAYTIME_SQL = """
    SELECT width_bucket(playtime_at_review_minutes, %(boundaries)s::int[]),  -- NULL playtime -> NULL
           count(*),
           count(*) FILTER (WHERE voted_up),
           avg(sentiment_compound)
    FROM reviews
    WHERE app_id = %(app_id)s AND sentiment_label IS NOT NULL
    GROUP BY 1
"""


@app.get("/games/{app_id}/playtime", response_model=Playtime)
def game_playtime(app_id: AppId, conn: Annotated[psycopg.Connection, Depends(get_conn)]):
    """Reviews grouped by how long the player had played when writing them (under 2 hours,
    2-10, 10-50, 50+), with how many recommend the game and the model's average score."""
    rows = {bucket: rest for bucket, *rest in
            conn.execute(PLAYTIME_SQL, {"app_id": app_id, "boundaries": playtime.BOUNDARIES})}
    if not rows:
        raise no_reviews(app_id)
    unknown = rows.pop(None, [0])[0]
    groups = []
    for index, group in enumerate(playtime.GROUPS):
        reviews, recommended, avg_score = rows.get(index, (0, 0, None))
        enough = reviews >= playtime.MIN_REVIEWS
        groups.append(PlaytimeGroupStats(
            group=group, reviews=reviews, recommended=recommended,
            recommended_pct=pct(recommended, reviews) if enough else None,
            avg_score=round(avg_score, 3) if enough else None,
        ))
    return Playtime(app_id=app_id, total_reviews=sum(g.reviews for g in groups) + unknown,
                    min_reviews=playtime.MIN_REVIEWS, unknown_playtime=unknown, groups=groups)


# ---------- GET /games/{app_id}/offtopic ----------

class OfftopicPeriod(BaseModel):
    start: datetime
    end: datetime              # for a period still going on, when Steam was asked
    reviews_left_out: int      # English reviews posted in the period that Steam leaves out by default
    negative_left_out: int     # how many of those are Not recommended
    still_flagged: bool        # the period was still going on when Steam was asked


class Offtopic(BaseModel):
    app_id: int
    checked_at: datetime          # when Steam was asked; answers are cached for an hour
    periods: list[OfftopicPeriod]  # oldest first; empty if Valve never flagged the game


@app.get("/games/{app_id}/offtopic", response_model=Offtopic)
def game_offtopic(app_id: AppId):
    """Periods Valve flagged as off-topic review activity (review bombs). Steam leaves every review
    posted in them out of its default results, so they're missing from the stored reviews too."""
    try:
        checked_at, periods = offtopic.offtopic_periods(app_id)
    except SteamRateLimited as error:
        raise HTTPException(429, "Steam is limiting requests right now. Try again in a minute.",
                            headers={"Retry-After": str(RATE_LIMIT_WAIT)}) from error
    except SteamError as error:
        raise HTTPException(502, f"Steam API error: {error}") from error
    return Offtopic(app_id=app_id, checked_at=checked_at, periods=[OfftopicPeriod(**p) for p in periods])


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
      AND (%(playtime)s::int IS NULL
           OR width_bucket(playtime_at_review_minutes, %(boundaries)s::int[]) = %(playtime)s)
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
    # ?playtime= in the URL; a different name here so it doesn't hide the playtime module
    playtime_group: Annotated[playtime.PlaytimeGroup | None, Query(alias="playtime")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    """Reviews for a game, newest first, optionally only one sentiment and/or one playtime group."""
    require_reviews(conn, app_id)
    params = {
        "app_id": app_id, "sentiment": sentiment, "limit": page_size, "offset": (page - 1) * page_size,
        # the group's position in playtime.GROUPS, which is what width_bucket returns
        "playtime": None if playtime_group is None else playtime.GROUPS.index(playtime_group),
        "boundaries": playtime.BOUNDARIES,
    }
    total = conn.execute(COUNT_REVIEWS_SQL, params).fetchone()[0]
    with conn.cursor(row_factory=dict_row) as cur:
        items = [Review(**row) for row in cur.execute(PAGE_REVIEWS_SQL, params)]
    return ReviewPage(app_id=app_id, page=page, page_size=page_size, total=total, items=items)
