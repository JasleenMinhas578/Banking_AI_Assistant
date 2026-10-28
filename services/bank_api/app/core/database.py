"""Database connection helper: one connection and one transaction per request."""

from collections.abc import Iterator

import psycopg

from app.core.config import settings
from app.core.exceptions import BankRefusal, DatabaseUnavailable


def get_connection() -> Iterator[psycopg.Connection]:
    """Open a connection for one request, then commit or roll back.

    - Request succeeds: commit.
    - BankRefusal (the bank said no on purpose): commit anyway, so the refusal
      is saved (audit row, failed-PIN counter), then pass the error on.
    - Anything else goes wrong: roll everything back.
    """
    try:
        conn = psycopg.connect(settings.database_url, connect_timeout=3)
    except psycopg.OperationalError as exc:
        raise DatabaseUnavailable() from exc

    with conn:  # commits on success, rolls back on error, always closes
        try:
            yield conn
        except BankRefusal:
            conn.commit()
            raise
