"""
Shared test setup.

Tests use a separate database named after yours plus "_test" (e.g. steam_reviews_test),
created automatically on the same server, so your real data is never touched.
Steam is never called: `fake_steam` replaces the HTTP requests with canned responses.
"""

from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app import db, steam
from app.main import app, get_conn

INIT_SQL = Path(__file__).resolve().parents[2] / "db" / "init.sql"


@pytest.fixture(scope="session")
def test_database_url() -> str:
    main_url = db.database_url()
    test_name = conninfo_to_dict(main_url)["dbname"] + "_test"
    with psycopg.connect(main_url, autocommit=True) as conn:  # CREATE DATABASE can't run in a transaction
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (test_name,)).fetchone():
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(test_name)))
    test_url = make_conninfo(main_url, dbname=test_name)
    with psycopg.connect(test_url) as conn:
        conn.execute(INIT_SQL.read_text())  # same schema as the real database
    return test_url


@pytest.fixture
def conn(test_database_url):
    """A connection to the test database, starting each test with empty tables."""
    with psycopg.connect(test_database_url) as conn:
        conn.execute("TRUNCATE reviews, review_topics, game_updates, update_review_days")
        conn.commit()
        yield conn


@pytest.fixture
def client(test_database_url, conn):
    """An API client whose requests use the test database."""
    def test_conn():
        with psycopg.connect(test_database_url) as c:
            yield c

    app.dependency_overrides[get_conn] = test_conn
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------- fake Steam ----------

@pytest.fixture
def fake_steam(monkeypatch):
    """
    Replace Steam with a queue of responses. Put FakeResponses (or exceptions to raise)
    in `responses`; each request takes the next one. `calls` and `sleeps` record what happened.
    """
    fake = SimpleNamespace(responses=[], calls=[], sleeps=[])

    def fake_get(url, params, timeout):
        fake.calls.append(params)
        result = fake.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(steam.requests, "get", fake_get)
    monkeypatch.setattr(steam.time, "sleep", fake.sleeps.append)  # record waits instead of waiting
    return fake
