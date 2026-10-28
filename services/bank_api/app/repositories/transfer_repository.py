"""SQL for transfers: locking, the daily total, and the money move itself."""

from datetime import datetime
from uuid import UUID

import psycopg
from psycopg.rows import class_row

from app.models.transfer import Transfer

_COLUMNS = "id, from_account_id, to_account_id, amount_cents, idempotency_key, status, created_at"


class TransferRepository:
    """Everything a transfer needs from the database."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def lock_customer(self, customer_id: UUID) -> None:
        """Lock the customer's row until this request's transaction ends.

        Two transfers for the same customer then run one after the other, so
        both can't pass the balance and daily-limit checks at the same moment.
        """
        self.conn.execute("select id from customers where id = %s for update", (customer_id,))

    def get_by_key(self, idempotency_key: str) -> Transfer | None:
        """The transfer already made with this Idempotency-Key, if any."""
        with self.conn.cursor(row_factory=class_row(Transfer)) as cur:
            cur.execute(
                f"select {_COLUMNS} from transfers where idempotency_key = %s",
                (idempotency_key,),
            )
            return cur.fetchone()

    def total_sent_since(self, customer_id: UUID, since: datetime) -> int:
        """Cents moved out of this customer's accounts since a moment in time."""
        row = self.conn.execute(
            """
            select coalesce(sum(t.amount_cents), 0)
              from transfers t
              join accounts a on a.id = t.from_account_id
             where a.customer_id = %s
               and t.created_at >= %s
               and t.status = 'completed'
            """,
            (customer_id, since),
        ).fetchone()
        return int(row[0]) if row else 0

    def execute(
        self,
        *,
        from_account_id: UUID,
        to_account_id: UUID,
        amount_cents: int,
        idempotency_key: str,
        debit_label: str,
        credit_label: str,
    ) -> Transfer:
        """Move the money. All five writes happen, or none of them do.

        conn.transaction() opens a savepoint: if any statement inside fails,
        everything inside is undone before the error goes any further.
        """
        with self.conn.transaction():
            self.conn.execute(
                "update accounts set balance_cents = balance_cents - %s where id = %s",
                (amount_cents, from_account_id),
            )
            self.conn.execute(
                "update accounts set balance_cents = balance_cents + %s where id = %s",
                (amount_cents, to_account_id),
            )
            self.conn.execute(
                """
                insert into transactions (account_id, merchant, amount_cents, status)
                values (%s, %s, %s, 'posted'), (%s, %s, %s, 'posted')
                """,
                (
                    from_account_id,
                    debit_label,
                    -amount_cents,
                    to_account_id,
                    credit_label,
                    amount_cents,
                ),
            )
            with self.conn.cursor(row_factory=class_row(Transfer)) as cur:
                cur.execute(
                    f"""
                    insert into transfers
                        (from_account_id, to_account_id, amount_cents, idempotency_key)
                    values (%s, %s, %s, %s)
                    returning {_COLUMNS}
                    """,
                    (from_account_id, to_account_id, amount_cents, idempotency_key),
                )
                transfer = cur.fetchone()
        if transfer is None:
            raise LookupError("transfer insert returned no row")
        return transfer
