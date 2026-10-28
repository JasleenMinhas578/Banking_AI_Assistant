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

    def lock_for_customer(self, account_ids: list[UUID], customer_id: UUID) -> dict[UUID, Account]:
        """Fetch and lock this customer's accounts among account_ids.

        Accounts that don't exist or belong to someone else are simply left
        out. FOR UPDATE holds the rows until the request's transaction ends,
        so no other request can change these balances in the meantime.
        Locking in id order means two requests never wait on each other in a
        circle (a deadlock).
        """
        with self.conn.cursor(row_factory=class_row(Account)) as cur:
            cur.execute(
                """
                select id, customer_id, account_type, last4, balance_cents
                  from accounts
                 where id = any(%s) and customer_id = %s
                 order by id
                   for update
                """,
                (account_ids, customer_id),
            )
            return {account.id: account for account in cur.fetchall()}

    def get_for_customer(self, account_id: UUID, customer_id: UUID) -> Account | None:
        """One account, but only if this customer owns it. None otherwise.

        The ownership check lives in the WHERE clause itself, so there's no
        way to fetch someone else's account and forget to check.
        """
        with self.conn.cursor(row_factory=class_row(Account)) as cur:
            cur.execute(
                """
                select id, customer_id, account_type, last4, balance_cents
                  from accounts
                 where id = %s and customer_id = %s
                """,
                (account_id, customer_id),
            )
            return cur.fetchone()
