"""SQL for the sessions table."""

from datetime import datetime
from uuid import UUID

import psycopg
from psycopg.rows import class_row

from app.models.session import OtpChallenge, Session

_COLUMNS = "id, customer_id, token, verified, step_up_verified, last_activity_at, expires_at"


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

    def set_otp(self, session_id: UUID, otp_hash: str, expires_at: datetime) -> None:
        """Store a new one-time code's hash, replacing any earlier code."""
        self.conn.execute(
            """
            update sessions
               set otp_hash = %s, otp_expires_at = %s, otp_attempts = 0
             where id = %s
            """,
            (otp_hash, expires_at, session_id),
        )

    def get_otp(self, session_id: UUID) -> OtpChallenge | None:
        """The code waiting to be checked, or None if there isn't one."""
        with self.conn.cursor(row_factory=class_row(OtpChallenge)) as cur:
            cur.execute(
                """
                select otp_hash, otp_expires_at, otp_attempts
                  from sessions
                 where id = %s and otp_hash is not null
                """,
                (session_id,),
            )
            return cur.fetchone()

    def record_otp_failure(self, session_id: UUID) -> int:
        """Count one wrong code. Returns the new number of wrong attempts."""
        row = self.conn.execute(
            """
            update sessions set otp_attempts = otp_attempts + 1
             where id = %s
         returning otp_attempts
            """,
            (session_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"session {session_id} disappeared")
        return int(row[0])

    def clear_otp(self, session_id: UUID) -> None:
        """Cancel the current code, so it can never be used."""
        self.conn.execute(
            """
            update sessions set otp_hash = null, otp_expires_at = null, otp_attempts = 0
             where id = %s
            """,
            (session_id,),
        )

    def mark_step_up_verified(self, session_id: UUID) -> Session:
        """The code was right: use it up and mark the session as stepped up."""
        return self._one(
            f"""
            update sessions
               set step_up_verified = true,
                   otp_hash = null, otp_expires_at = null, otp_attempts = 0
             where id = %s
         returning {_COLUMNS}
            """,
            (session_id,),
        )

    def _one(self, sql: str, params: tuple[object, ...]) -> Session:
        """Run a statement that must return exactly one session row."""
        with self.conn.cursor(row_factory=class_row(Session)) as cur:
            cur.execute(sql, params)
            session = cur.fetchone()
        if session is None:
            raise LookupError("expected a session row, got none")
        return session
