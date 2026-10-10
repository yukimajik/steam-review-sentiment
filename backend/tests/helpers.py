"""Helpers for building test data: reviews in the database, and fake Steam responses."""

from datetime import datetime, timezone


def add_review(conn, review_id, app_id=620, voted_up=True, label="positive", compound=0.5,
               created_at=datetime(2026, 8, 15, tzinfo=timezone.utc), text="text", helpful_votes=0):
    """Insert a review with a known sentiment (bypassing the model) so expected numbers are exact."""
    conn.execute(
        """INSERT INTO reviews (recommendation_id, app_id, review_text, voted_up, created_at,
                                sentiment_label, sentiment_compound, helpful_votes)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (review_id, app_id, text, voted_up, created_at, label, compound, helpful_votes),
    )
    conn.commit()


def add_topic(conn, review_id, topic, label="positive", score=0.5, excerpt="excerpt"):
    """Tag a stored review with a topic and that topic's sentiment (bypassing the keywords and model)."""
    conn.execute(
        """INSERT INTO review_topics (recommendation_id, topic, excerpt, sentiment_score, sentiment_label)
           VALUES (%s, %s, %s, %s, %s)""",
        (review_id, topic, excerpt, score, label),
    )
    conn.commit()


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self.payload = payload
        self.headers = headers or {}

    def json(self):
        if self.payload is None:
            raise ValueError("not JSON")
        return self.payload


def steam_review(review_id, text="Great game", voted_up=True, timestamp=1754000000):
    """One review in the shape of Steam's JSON."""
    return {"recommendationid": str(review_id), "review": text, "voted_up": voted_up,
            "author": {"playtime_at_review": 120}, "votes_up": 3, "timestamp_created": timestamp}


def steam_page(reviews, cursor="next"):
    return FakeResponse(payload={"success": 1, "reviews": reviews, "cursor": cursor})


def store_item(app_id, name, item_type="app"):
    """One result in the shape of Steam's store search JSON."""
    return {"type": item_type, "id": app_id, "name": name, "tiny_image": f"https://img.example.test/{app_id}.jpg"}


def store_search_page(items):
    return FakeResponse(payload={"total": len(items), "items": items})


def add_update(conn, gid, posted_at, title="Patch 1.0.0", app_id=620):
    """Store an update post, as if found in the game's Steam news."""
    conn.execute(
        "INSERT INTO game_updates (gid, app_id, title, url, posted_at) VALUES (%s, %s, %s, %s, %s)",
        (gid, app_id, title, f"https://steam.example.test/news/{gid}", posted_at),
    )
    conn.commit()


def mark_days_fetched(conn, days, app_id=620):
    """Record days as if their reviews had been fetched for the before/after comparison."""
    for day in days:
        conn.execute("INSERT INTO update_review_days (app_id, day) VALUES (%s, %s)", (app_id, day))
    conn.commit()


def news_item(gid, title, posted_at, tags=()):
    """One official news post in the shape of Steam's GetNewsForApp JSON."""
    return {"gid": str(gid), "title": title, "url": f"https://steam.example.test/news/{gid}",
            "date": int(posted_at.timestamp()), "feedname": "steam_community_announcements", "tags": list(tags)}


def news_page(items):
    return FakeResponse(payload={"appnews": {"appid": 620, "newsitems": items, "count": len(items)}})
