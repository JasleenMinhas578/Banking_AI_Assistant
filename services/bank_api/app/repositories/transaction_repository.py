"""SQL for the transactions table."""

from uuid import UUID

import psycopg
from psycopg.rows import class_row

from app.models.transaction import Transaction


class TransactionRepository:
    """Reads an account's transaction history."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def list_for_account(self, account_id: UUID, limit: int) -> list[Transaction]:
        """The most recent transactions on one account, newest first.

        This doesn't check ownership. The service must do that first.
        """
        with self.conn.cursor(row_factory=class_row(Transaction)) as cur:
            cur.execute(
                """
                select id, account_id, merchant, amount_cents, status, posted_at
                  from transactions
                 where account_id = %s
                 order by posted_at desc, id
                 limit %s
                """,
                (account_id, limit),
            )
            return cur.fetchall()

    def get_for_customer(self, transaction_id: UUID, customer_id: UUID) -> Transaction | None:
        """One transaction, but only if it's on one of this customer's accounts.

        Ownership goes two steps: transaction -> account -> customer.
        """
        with self.conn.cursor(row_factory=class_row(Transaction)) as cur:
            cur.execute(
                """
                select t.id, t.account_id, t.merchant, t.amount_cents, t.status, t.posted_at
                  from transactions t
                  join accounts a on a.id = t.account_id
                 where t.id = %s and a.customer_id = %s
                """,
                (transaction_id, customer_id),
            )
            return cur.fetchone()
