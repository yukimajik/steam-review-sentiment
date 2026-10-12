"""
Periods Valve flagged as off-topic review activity ("review bombs"), and how many reviews each
one leaves out.

During a flagged period Steam leaves every review out of its default results, and this app
fetches with the defaults, so those reviews are missing from our charts too. Showing the periods
explains the gap. Results are cached for an hour, so reloading a dashboard doesn't ask Steam again.
"""

import threading
import time
from datetime import datetime, timedelta, timezone

from app.steam import count_reviews, fetch_offtopic_periods

CACHE_SECONDS = 60 * 60
CACHE_MAX_ENTRIES = 1000  # oldest entries are dropped past this, so memory can't grow forever
# Steam reports a period that's still going on as ending at the moment of the request. Allow
# for the two clocks (ours and Steam's) differing a little.
STILL_FLAGGED_TOLERANCE = timedelta(minutes=5)

_cache: dict[int, tuple[float, datetime, list[dict]]] = {}  # app ID -> (time stored, checked at, periods)
_cache_lock = threading.Lock()  # FastAPI runs requests in parallel threads


def check_periods(app_id: int) -> tuple[datetime, list[dict]]:
    """Ask Steam: one request for the periods, then two per period (counts without and with off-topic reviews)."""
    checked_at = datetime.now(timezone.utc)
    periods = []
    for start, end in fetch_offtopic_periods(app_id):
        counted, counted_negative = count_reviews(app_id, start, end, include_offtopic=False)
        everything, everything_negative = count_reviews(app_id, start, end, include_offtopic=True)
        periods.append({
            "start": start,
            "end": end,
            "reviews_left_out": max(everything - counted, 0),
            "negative_left_out": max(everything_negative - counted_negative, 0),
            "still_flagged": end >= checked_at - STILL_FLAGGED_TOLERANCE,
        })
    return checked_at, periods


def offtopic_periods(app_id: int) -> tuple[datetime, list[dict]]:
    """(when Steam was asked, the game's flagged periods), from the cache if asked within the last hour."""
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(app_id)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1], hit[2]
    checked_at, periods = check_periods(app_id)  # outside the lock, so a slow Steam call doesn't block other games
    with _cache_lock:
        _cache.pop(app_id, None)  # re-insert so it counts as newest
        _cache[app_id] = (now, checked_at, periods)
        while len(_cache) > CACHE_MAX_ENTRIES:
            del _cache[next(iter(_cache))]  # dicts keep insertion order, so this is the oldest
    return checked_at, periods


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
