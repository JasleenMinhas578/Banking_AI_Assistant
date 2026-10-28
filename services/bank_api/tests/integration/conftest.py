"""Shared setup for tests that use the real local database.

Every test starts from a freshly seeded bank, so tests can't affect each other.
Note: this resets your demo data, exactly like `uv run python scripts/seed.py`.
If Supabase isn't running, these tests are skipped instead of failing.
"""

from collections.abc import Iterator
from functools import cache

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from scripts.seed import main as seed_database


@cache
def _database_is_up() -> bool:
    try:
        with psycopg.connect(settings.database_url, connect_timeout=2):
            return True
    except psycopg.OperationalError:
        return False


@pytest.fixture(autouse=True)
def fresh_bank() -> None:
    """Skip if the database is down; otherwise reseed it."""
    if not _database_is_up():
        pytest.skip("Supabase isn't running. Start it with `supabase start`.")
    seed_database()


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Calls the API in-process, no server needed."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db() -> Iterator[psycopg.Connection]:
    """A direct connection, to check what the API actually saved."""
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        yield conn
