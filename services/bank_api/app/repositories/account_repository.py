"""SQL for the accounts table."""

from uuid import UUID

import psycopg
from psycopg.rows import class_row

from app.models.account import Account


class AccountRepository:
    """Reads accounts. Every query is scoped to one customer."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def list_for_customer(self, customer_id: UUID) -> list[Account]:
        """All accounts belonging to this customer, chequing first."""
        with self.conn.cursor(row_factory=class_row(Account)) as cur:
            cur.execute(
                """
                select id, customer_id, account_type, last4, balance_cents
                  from accounts
                 where customer_id = %s
                 order by account_type, created_at
                """,
                (customer_id,),
            )
            return cur.fetchall()
