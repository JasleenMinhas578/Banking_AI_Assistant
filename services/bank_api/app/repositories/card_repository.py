"""SQL for the cards table.

A card belongs to an account, and an account belongs to a customer, so every
ownership check joins cards to accounts.
"""

from uuid import UUID

import psycopg
from psycopg.rows import class_row

from app.models.card import Card

_COLUMNS = "c.id, c.account_id, c.last4, c.status, c.frozen_at"


class CardRepository:
    """Reads cards and freezes them. There is deliberately no unfreeze."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def list_for_customer(self, customer_id: UUID) -> list[Card]:
        """All cards on this customer's accounts."""
        with self.conn.cursor(row_factory=class_row(Card)) as cur:
            cur.execute(
                f"""
                select {_COLUMNS}
                  from cards c
                  join accounts a on a.id = c.account_id
                 where a.customer_id = %s
                 order by a.account_type, c.last4
                """,
                (customer_id,),
            )
            return cur.fetchall()

    def get_for_customer(self, card_id: UUID, customer_id: UUID) -> Card | None:
        """One card, but only if it's on one of this customer's accounts."""
        with self.conn.cursor(row_factory=class_row(Card)) as cur:
            cur.execute(
                f"""
                select {_COLUMNS}
                  from cards c
                  join accounts a on a.id = c.account_id
                 where c.id = %s and a.customer_id = %s
                """,
                (card_id, customer_id),
            )
            return cur.fetchone()

    def freeze(self, card_id: UUID) -> Card | None:
        """Freeze an active card. Returns None if it was already frozen.

        "and status = 'active'" makes this safe to repeat: a second freeze
        matches no row and changes nothing.
        """
        with self.conn.cursor(row_factory=class_row(Card)) as cur:
            cur.execute(
                """
                update cards c
                   set status = 'frozen', frozen_at = now()
                 where c.id = %s and c.status = 'active'
             returning c.id, c.account_id, c.last4, c.status, c.frozen_at
                """,
                (card_id,),
            )
            return cur.fetchone()
