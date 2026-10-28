"""SQL for the sessions table."""

from datetime import datetime
from uuid import UUID

import psycopg
from psycopg.rows import class_row

from app.models.session import Session

_COLUMNS = (
    "id, customer_id, token, verified, step_up_verified, last_activity_at, expires_at"
)


class SessionRepository:
    """Creates, finds and updates call sessions."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def create(self, token: str, now: datetime, expires_at: datetime) -> Session:
        """Start a new, unverified session."""
        return self._one(
            f"""
            insert into sessions (token, last_activity_at, expires_at)
            values (%s, %s, %s)
            returning {_COLUMNS}
            """,
            (token, now, expires_at),
        )

    def get_by_token(self, token: str) -> Session | None:
        """Find a session by its token. None if there's no match."""
        with self.conn.cursor(row_factory=class_row(Session)) as cur:
            cur.execute(f"select {_COLUMNS} from sessions where token = %s", (token,))
            return cur.fetchone()

    def touch(self, session_id: UUID, now: datetime, expires_at: datetime) -> Session:
        """Record activity and push the idle timeout back."""
        return self._one(
            f"""
            update sessions set last_activity_at = %s, expires_at = %s
             where id = %s
         returning {_COLUMNS}
            """,
            (now, expires_at, session_id),
        )

    def mark_verified(self, session_id: UUID, customer_id: UUID) -> Session:
        """Bind the session to a customer once their PIN is correct."""
        return self._one(
            f"""
            update sessions set customer_id = %s, verified = true
             where id = %s
         returning {_COLUMNS}
            """,
            (customer_id, session_id),
        )

    def _one(self, sql: str, params: tuple[object, ...]) -> Session:
        """Run a statement that must return exactly one session row."""
        with self.conn.cursor(row_factory=class_row(Session)) as cur:
            cur.execute(sql, params)
            session = cur.fetchone()
        if session is None:
            raise LookupError("expected a session row, got none")
        return session
