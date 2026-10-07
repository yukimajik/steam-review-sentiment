"""Fetch English reviews for one game from Steam's public reviews API."""

import logging
import time
from datetime import datetime, timezone

import requests

STEAM_REVIEWS_URL = "https://store.steampowered.com/appreviews/{app_id}"
PAGE_SIZE = 100            # Steam's maximum reviews per request
DELAY_BETWEEN_PAGES = 1.0  # seconds; be polite to Steam's servers
MAX_RETRIES = 3
MAX_RETRY_WAIT = 60        # seconds; cap on how long a Retry-After header can make us wait

logger = logging.getLogger(__name__)


class SteamError(Exception):
    """Steam's API failed, or sent back something we can't use."""


def is_retryable(status: int) -> bool:
    """429 means we're being rate limited and 5xx means Steam's servers are having trouble.
    Other errors (e.g. 404) won't fix themselves, so retrying them only wastes time."""
    return status == 429 or status >= 500


def retry_wait(attempt: int, retry_after: str | None) -> float:
    """Seconds to wait before the next try: Steam's Retry-After header if it sent one,
    otherwise exponential backoff (2s, then 4s)."""
    if retry_after and retry_after.isdigit():
        return min(int(retry_after), MAX_RETRY_WAIT)
    return 2 ** attempt


def fetch_page(app_id: int, cursor: str) -> dict:
    """Request one page of reviews, retrying on network errors, rate limits and server errors."""
    params = {
        "json": 1,
        "language": "english",
        "filter": "recent",       # newest first; gives stable cursor pagination
        "review_type": "all",     # positive and negative
        "purchase_type": "all",   # bought on Steam or elsewhere
        "num_per_page": PAGE_SIZE,
        "cursor": cursor,         # requests URL-encodes this (cursors contain + / =)
    }
    url = STEAM_REVIEWS_URL.format(app_id=app_id)

    for attempt in range(1, MAX_RETRIES + 1):
        retry_after = None
        try:
            response = requests.get(url, params=params, timeout=30)
        except (requests.ConnectionError, requests.Timeout) as error:
            problem = f"network error: {error}"
        else:
            if response.status_code == 200:
                return parse_page(response, app_id)
            if not is_retryable(response.status_code):
                raise SteamError(f"Steam returned HTTP {response.status_code} for app {app_id}")
            problem = f"HTTP {response.status_code}"
            retry_after = response.headers.get("Retry-After")

        if attempt == MAX_RETRIES:
            raise SteamError(f"Steam request for app {app_id} failed {MAX_RETRIES} times ({problem})")
        wait = retry_wait(attempt, retry_after)
        logger.warning("Steam request failed (%s), retrying in %ss...", problem, wait)
        time.sleep(wait)


def parse_page(response: requests.Response, app_id: int) -> dict:
    """Read Steam's JSON, checking it's a successful answer."""
    try:
        data = response.json()
    except ValueError as error:  # e.g. an HTML error page instead of JSON
        raise SteamError(f"Steam sent a response that isn't JSON for app {app_id}") from error
    if data.get("success") != 1:
        raise SteamError(f"Steam returned success={data.get('success')} for app {app_id}")
    return data


def fetch_reviews(app_id: int, max_reviews: int):
    """
    Yield reviews one page at a time, following Steam's cursor until there are
    no more reviews or we reach max_reviews.
    """
    cursor = "*"  # "*" means "start from the beginning"
    fetched = 0

    while fetched < max_reviews:
        data = fetch_page(app_id, cursor)
        reviews = data.get("reviews", [])
        if not reviews:
            break  # nothing left to fetch

        reviews = reviews[: max_reviews - fetched]  # don't go past the limit
        yield reviews
        fetched += len(reviews)

        next_cursor = data["cursor"]
        if next_cursor == cursor:
            break  # Steam repeats the cursor when there are no further pages
        cursor = next_cursor
        if fetched < max_reviews:
            time.sleep(DELAY_BETWEEN_PAGES)


def to_row(app_id: int, review: dict) -> tuple:
    """Pick out the fields we store from one review in Steam's JSON."""
    return (
        int(review["recommendationid"]),              # Steam sends IDs as strings
        app_id,
        review["review"],
        review["voted_up"],
        review["author"].get("playtime_at_review"),   # minutes; not always present
        review.get("votes_up", 0),
        datetime.fromtimestamp(review["timestamp_created"], tz=timezone.utc),  # Unix seconds -> datetime
    )
