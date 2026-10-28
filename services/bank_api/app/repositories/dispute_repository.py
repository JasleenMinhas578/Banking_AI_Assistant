"""SQL for the disputes table."""

from uuid import UUID

import psycopg
from psycopg.rows import class_row

from app.models.dispute import Dispute

# Every read joins the transaction, so a dispute always carries its merchant and amount.
_SELECT = """
    select d.id, d.transaction_id, d.reason, d.status, d.created_at,
           t.merchant, t.amount_cents
      from disputes d
      join transactions t on t.id = d.transaction_id
"""


class DisputeRepository:
    """Opens and reads disputes."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def create(self, transaction_id: UUID, reason: str) -> bool:
        """Open a dispute. Returns False if one already exists for this transaction.

        The table's UNIQUE (transaction_id) constraint decides, not our code.
        "on conflict do nothing" means two requests at the same moment can't
        both create one: the database lets exactly one through.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                insert into disputes (transaction_id, reason) values (%s, %s)
                on conflict (transaction_id) do nothing
                returning id
                """,
                (transaction_id, reason),
            )
            return cur.fetchone() is not None

    def get_by_transaction(self, transaction_id: UUID) -> Dispute | None:
        """The dispute on this transaction, if there is one."""
        with self.conn.cursor(row_factory=class_row(Dispute)) as cur:
            cur.execute(_SELECT + " where d.transaction_id = %s", (transaction_id,))
            return cur.fetchone()

    def list_for_customer(self, customer_id: UUID) -> list[Dispute]:
        """All disputes on this customer's accounts, newest first."""
        with self.conn.cursor(row_factory=class_row(Dispute)) as cur:
            cur.execute(
                _SELECT
                + """
                  join accounts a on a.id = t.account_id
                 where a.customer_id = %s
                 order by d.created_at desc
                """,
                (customer_id,),
            )
            return cur.fetchall()
