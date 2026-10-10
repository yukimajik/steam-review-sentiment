"""Steam API client: retries, rate limits, and bad responses (Steam is faked, see conftest.py)."""

import pytest
import requests

from app.steam import MAX_RETRY_WAIT, SteamError, SteamRateLimited, fetch_page, fetch_reviews
from tests.helpers import FakeResponse, steam_page, steam_review


def test_returns_page(fake_steam):
    fake_steam.responses = [steam_page([steam_review(1)], cursor="abc")]
    data = fetch_page(620, "*")
    assert data["cursor"] == "abc"
    assert fake_steam.calls[0]["cursor"] == "*"


def test_rate_limit_waits_for_retry_after_then_retries(fake_steam):
    fake_steam.responses = [FakeResponse(429, headers={"Retry-After": "7"}), steam_page([])]
    fetch_page(620, "*")
    assert len(fake_steam.calls) == 2
    assert fake_steam.sleeps == [7]


def test_retry_after_is_capped(fake_steam):
    fake_steam.responses = [FakeResponse(429, headers={"Retry-After": "3600"}), steam_page([])]
    fetch_page(620, "*")
    assert fake_steam.sleeps == [MAX_RETRY_WAIT]


def test_server_errors_back_off_then_give_up(fake_steam):
    fake_steam.responses = [FakeResponse(503), FakeResponse(503), FakeResponse(503)]
    with pytest.raises(SteamError, match="failed 3 times"):
        fetch_page(620, "*")
    assert fake_steam.sleeps == [2, 4]  # exponential backoff between the 3 tries


def test_network_error_is_retried(fake_steam):
    fake_steam.responses = [requests.ConnectionError("connection reset"), steam_page([])]
    fetch_page(620, "*")
    assert len(fake_steam.calls) == 2


def test_client_error_is_not_retried(fake_steam):
    fake_steam.responses = [FakeResponse(404)]
    with pytest.raises(SteamError, match="HTTP 404"):
        fetch_page(620, "*")
    assert len(fake_steam.calls) == 1


def test_response_that_is_not_json(fake_steam):
    fake_steam.responses = [FakeResponse(200, payload=None)]
    with pytest.raises(SteamError, match="isn't JSON"):
        fetch_page(620, "*")


def test_unsuccessful_answer(fake_steam):
    fake_steam.responses = [FakeResponse(200, payload={"success": 2})]
    with pytest.raises(SteamError, match="success=2"):
        fetch_page(620, "*")


def test_follows_cursor_until_no_more_reviews(fake_steam):
    fake_steam.responses = [
        steam_page([steam_review(1), steam_review(2)], cursor="A"),
        steam_page([steam_review(3)], cursor="B"),
        steam_page([], cursor="C"),
    ]
    pages = list(fetch_reviews(620, max_reviews=1000))
    assert [len(page) for page in pages] == [2, 1]
    assert [call["cursor"] for call in fake_steam.calls] == ["*", "A", "B"]


def test_stops_at_max_reviews(fake_steam):
    fake_steam.responses = [steam_page([steam_review(1), steam_review(2), steam_review(3)])]
    pages = list(fetch_reviews(620, max_reviews=2))
    assert [len(page) for page in pages] == [2]
    assert len(fake_steam.calls) == 1


def test_rate_limit_that_doesnt_lift_is_reported_as_such(fake_steam):
    fake_steam.responses = [FakeResponse(429)] * 3
    with pytest.raises(SteamRateLimited, match="HTTP 429"):
        fetch_page(620, "*")
