"""
Game search by name, built on Steam's store search, with a cache and a typo fallback.

Steam's search doesn't forgive typos inside a word ("cyberpnk" finds nothing), but it
does match partial words ("cyberp" finds Cyberpunk 2077). So when a search finds
nothing, we retry with the last letter removed, a few times.
"""

import threading
import time

from app.steam import search_store

CACHE_SECONDS = 60 * 60  # Steam's results rarely change within an hour
CACHE_MAX_ENTRIES = 1000  # oldest entries are dropped past this, so memory can't grow forever
MAX_TYPO_RETRIES = 3      # how many times to drop the last letter when nothing matches
MIN_FALLBACK_LENGTH = 3   # never shorten a search below this many characters

_cache: dict[str, tuple[float, list[dict]]] = {}  # query -> (time stored, results)
_cache_lock = threading.Lock()  # FastAPI runs requests in parallel threads


def normalize(query: str) -> str:
    """Lowercase and collapse spaces, so "  Portal " and "portal" share a cache entry."""
    return " ".join(query.split()).lower()


def cached_search(query: str) -> list[dict]:
    """Steam's results for one query, from the cache if we asked within the last hour."""
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(query)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    results = search_store(query)  # outside the lock, so one slow Steam call doesn't block other searches
    with _cache_lock:
        _cache.pop(query, None)  # re-insert so it counts as newest
        _cache[query] = (now, results)
        while len(_cache) > CACHE_MAX_ENTRIES:
            del _cache[next(iter(_cache))]  # dicts keep insertion order, so this is the oldest
    return results


def search_games(query: str) -> tuple[str, list[dict]]:
    """
    Return (the query that produced the results, results). The two queries differ only
    when the typo fallback kicked in; if nothing matches at all, it's the original query.
    """
    query = normalize(query)
    attempt = query
    for _ in range(MAX_TYPO_RETRIES + 1):
        results = cached_search(attempt)
        if results:
            return attempt, results
        shorter = attempt[:-1].rstrip()
        if len(shorter) < MIN_FALLBACK_LENGTH:
            break
        attempt = shorter
    return query, []


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
