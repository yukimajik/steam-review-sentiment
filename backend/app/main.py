"""
REST API for the Steam review sentiment dashboard.

Run it (from the project root):
    uvicorn --app-dir backend app.main:app --reload
Interactive docs: http://localhost:8000/docs
"""

import os
from datetime import datetime
from typing import Annotated, Literal

import psycopg
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from pydantic import BaseModel

from app import db
from app.steam import SteamError, fetch_reviews, to_row

MAX_FETCH = 5000  # the fetch request waits until done, so cap how long that can take

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


def pct(part: int, whole: int) -> float:
    return round(100 * part / whole, 1)


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
        # Steam answers success=1 with no reviews even for app IDs that don't exist
        raise HTTPException(404, f"Steam has no English reviews for app {app_id}. Double-check the app ID.")

    scored = db.score_reviews(conn, app_id=app_id)
    return FetchResult(app_id=app_id, fetched=fetched, new=new, scored=scored)


# ---------- GET /games/{app_id}/summary ----------

class Summary(BaseModel):
    app_id: int
    total_reviews: int
    positive_pct: float
    neutral_pct: float
    negative_pct: float
    agreement_pct: float  # VADER's label matches the player's vote; neutral counts as a miss
    baseline_pct: float   # what always guessing the more common vote would score


SUMMARY_SQL = """
    SELECT count(*),
           count(*) FILTER (WHERE sentiment_label = 'positive'),
           count(*) FILTER (WHERE sentiment_label = 'neutral'),
           count(*) FILTER (WHERE sentiment_label = 'negative'),
           count(*) FILTER (WHERE voted_up),
           -- agreement: VADER positive = Recommended, VADER negative = Not recommended
           count(*) FILTER (WHERE (voted_up AND sentiment_label = 'positive')
                               OR (NOT voted_up AND sentiment_label = 'negative'))
    FROM reviews
    WHERE app_id = %s AND sentiment_label IS NOT NULL
"""


@app.get("/games/{app_id}/summary", response_model=Summary)
def game_summary(app_id: AppId, conn: Annotated[psycopg.Connection, Depends(get_conn)]):
    """Review count, sentiment split, and how often VADER agrees with the players' own votes."""
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

class TrendMonth(BaseModel):
    month: str           # e.g. "2026-08"
    avg_compound: float  # average VADER score, -1 to +1
    review_count: int    # so a month with a handful of reviews isn't read like one with hundreds


class Trend(BaseModel):
    app_id: int
    months: list[TrendMonth]


# Months are in UTC so the result doesn't depend on the database server's time zone.
TREND_SQL = """
    SELECT to_char(date_trunc('month', created_at AT TIME ZONE 'UTC'), 'YYYY-MM'),
           avg(sentiment_compound),
           count(*)
    FROM reviews
    WHERE app_id = %s AND sentiment_label IS NOT NULL
    GROUP BY 1
    ORDER BY 1
"""


@app.get("/games/{app_id}/trend", response_model=Trend)
def game_trend(app_id: AppId, conn: Annotated[psycopg.Connection, Depends(get_conn)]):
    """Average sentiment for each month, by the date reviews were posted."""
    rows = conn.execute(TREND_SQL, (app_id,)).fetchall()
    if not rows:
        raise no_reviews(app_id)
    months = [TrendMonth(month=month, avg_compound=round(avg, 3), review_count=count) for month, avg, count in rows]
    return Trend(app_id=app_id, months=months)


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


HAS_REVIEWS_SQL = "SELECT EXISTS (SELECT 1 FROM reviews WHERE app_id = %s AND sentiment_label IS NOT NULL)"

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
    if not conn.execute(HAS_REVIEWS_SQL, (app_id,)).fetchone()[0]:
        raise no_reviews(app_id)
    params = {"app_id": app_id, "sentiment": sentiment, "limit": page_size, "offset": (page - 1) * page_size}
    total = conn.execute(COUNT_REVIEWS_SQL, params).fetchone()[0]
    with conn.cursor(row_factory=dict_row) as cur:
        items = [Review(**row) for row in cur.execute(PAGE_REVIEWS_SQL, params)]
    return ReviewPage(app_id=app_id, page=page, page_size=page_size, total=total, items=items)
