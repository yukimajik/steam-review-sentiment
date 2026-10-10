"""Talks to Steam: fetches a game's English reviews and its official news, and searches the store by name."""

import logging
import time
from datetime import date, datetime, time as day_time, timezone

import requests

STEAM_REVIEWS_URL = "https://store.steampowered.com/appreviews/{app_id}"
STORE_SEARCH_URL = "https://store.steampowered.com/api/storesearch/"  # undocumented, used by the store's own search box
NEWS_URL = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
NEWS_COUNT = 100           # official posts to read; covers 12 months for every game we checked
PAGE_SIZE = 100            # Steam's maximum reviews per request
DELAY_BETWEEN_PAGES = 1.0  # seconds; be polite to Steam's servers
MAX_RETRIES = 3
MAX_RETRY_WAIT = 60        # seconds; cap on how long a Retry-After header can make us wait
# Search runs while someone types, so it gives up sooner than fetching does (worst case ~12s, not ~96s)
SEARCH_TIMEOUT = 5         # seconds per attempt
SEARCH_RETRIES = 2

logger = logging.getLogger(__name__)


class SteamError(Exception):
    """Steam's API failed, or sent back something we can't use."""


class SteamRateLimited(SteamError):
    """Steam kept answering 429 Too Many Requests. In real runs that lasted a minute or two."""


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


def get_json(url: str, params: dict, what: str, timeout: float = 30, max_retries: int = MAX_RETRIES) -> dict:
    """
    GET a Steam URL and return its JSON, retrying on network errors, rate limits and
    server errors. `what` names the request in error messages, e.g. "app 620".
    """
    for attempt in range(1, max_retries + 1):
        retry_after = None
        status = None
        try:
            response = requests.get(url, params=params, timeout=timeout)
        except (requests.ConnectionError, requests.Timeout) as error:
            problem = f"network error: {error}"
        else:
            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError as error:  # e.g. an HTML error page instead of JSON
                    raise SteamError(f"Steam sent a response that isn't JSON for {what}") from error
            if not is_retryable(response.status_code):
                raise SteamError(f"Steam returned HTTP {response.status_code} for {what}")
            status = response.status_code
            problem = f"HTTP {status}"
            retry_after = response.headers.get("Retry-After")

        if attempt == max_retries:
            error = SteamRateLimited if status == 429 else SteamError
            raise error(f"Steam request for {what} failed {max_retries} times ({problem})")
        wait = retry_wait(attempt, retry_after)
        logger.warning("Steam request failed (%s), retrying in %ss...", problem, wait)
        time.sleep(wait)


def fetch_page(app_id: int, cursor: str) -> dict:
    """Request one page of reviews."""
    params = {
        "json": 1,
        "language": "english",
        "filter": "recent",       # newest first; gives stable cursor pagination
        "review_type": "all",     # positive and negative
        "purchase_type": "all",   # bought on Steam or elsewhere
        "num_per_page": PAGE_SIZE,
        "cursor": cursor,         # requests URL-encodes this (cursors contain + / =)
    }
    data = get_json(STEAM_REVIEWS_URL.format(app_id=app_id), params, f"app {app_id}")
    if data.get("success") != 1:
        raise SteamError(f"Steam returned success={data.get('success')} for app {app_id}")
    return data


def fetch_reviews_on_day(app_id: int, day: date) -> list[dict]:
    """
    Up to 100 of the reviews posted on one day (UTC), newest first. Uses the date range
    the Steam store's own review filter uses; it isn't in Valve's documentation, so the
    answer is checked: if none of the reviews are from that day, Steam ignored the range.
    """
    start = int(datetime.combine(day, day_time(), tzinfo=timezone.utc).timestamp())
    end = start + 24 * 60 * 60 - 1
    params = {
        "json": 1,
        "language": "english",
        "filter": "recent",
        "review_type": "all",
        "purchase_type": "all",
        "num_per_page": PAGE_SIZE,
        "cursor": "*",
        "start_date": start,
        "end_date": end,
        "date_range_type": "include",
    }
    data = get_json(STEAM_REVIEWS_URL.format(app_id=app_id), params, f"app {app_id} on {day}")
    if data.get("success") != 1:
        raise SteamError(f"Steam returned success={data.get('success')} for app {app_id} on {day}")
    reviews = data.get("reviews", [])
    on_day = [r for r in reviews if start <= r["timestamp_created"] <= end]
    if reviews and not on_day:
        raise SteamError(f"Steam ignored the date range for app {app_id} on {day}")
    return on_day


def fetch_news(app_id: int) -> list[dict]:
    """A game's latest official announcements (no press articles), newest first:
    each with its id, title, link, time posted and Steam's tags (e.g. "patchnotes")."""
    params = {"appid": app_id, "count": NEWS_COUNT, "maxlength": 1, "feeds": "steam_community_announcements"}
    data = get_json(NEWS_URL, params, f"news for app {app_id}")
    try:
        items = data["appnews"]["newsitems"]
    except (KeyError, TypeError) as error:
        raise SteamError(f"Steam sent news in an unexpected format for app {app_id}") from error
    return [
        {
            "gid": item["gid"],
            "title": item["title"],
            "url": item["url"],
            "posted_at": datetime.fromtimestamp(item["date"], tz=timezone.utc),
            "tags": item.get("tags", []),
        }
        for item in items
    ]


def search_store(term: str) -> list[dict]:
    """
    Search the Steam store by name: at most 10 results, most relevant first.
    Includes DLC, demos and soundtracks (Steam labels them all "app"); packages
    and bundles are dropped because their IDs aren't app IDs.
    """
    params = {"term": term, "l": "english", "cc": "US"}
    data = get_json(STORE_SEARCH_URL, params, f'search "{term}"', timeout=SEARCH_TIMEOUT, max_retries=SEARCH_RETRIES)
    return [
        {"app_id": item["id"], "name": item["name"], "image_url": item.get("tiny_image")}
        for item in data.get("items", [])
        if item.get("type") == "app"
    ]


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
