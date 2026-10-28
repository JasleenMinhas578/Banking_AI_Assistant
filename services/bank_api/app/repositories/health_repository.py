"""Repository layer for the health check: the only place that touches SQL."""

import psycopg

from app.core.exceptions import DatabaseUnavailable


class HealthRepository:
    """Asks the database whether it's alive."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def ping(self) -> None:
        """Run the simplest possible query. Raises DatabaseUnavailable if it fails."""
        try:
            self.conn.execute("select 1")
        except psycopg.OperationalError as exc:
            raise DatabaseUnavailable() from exc
