"""SQL for the audit_log table. Rows are only ever added, never changed."""

from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb


class AuditRepository:
    """Writes one row per action: who tried what, and whether it was allowed."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def record(
        self,
        *,
        session_id: UUID | None,
        actor: str,
        action: str,
        outcome: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Add an audit row. Never put a PIN or full card number in details."""
        self.conn.execute(
            """
            insert into audit_log (session_id, actor, action, outcome, details)
            values (%s, %s, %s, %s, %s)
            """,
            (session_id, actor, action, outcome, Jsonb(details or {})),
        )
