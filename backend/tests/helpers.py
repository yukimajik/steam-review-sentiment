"""Helpers for building test data: reviews in the database, and fake Steam responses."""

from datetime import datetime, timezone


def add_review(conn, review_id, app_id=620, voted_up=True, label="positive", compound=0.5,
               created_at=datetime(2026, 8, 15, tzinfo=timezone.utc), text="text"):
    """Insert a review with a known sentiment (bypassing VADER) so expected numbers are exact."""
    conn.execute(
        """INSERT INTO reviews (recommendation_id, app_id, review_text, voted_up, created_at,
                                sentiment_label, sentiment_compound)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (review_id, app_id, text, voted_up, created_at, label, compound),
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
