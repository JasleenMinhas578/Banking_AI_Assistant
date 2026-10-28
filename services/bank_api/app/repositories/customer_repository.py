"""SQL for the customers table."""

from uuid import UUID

import psycopg
from psycopg.rows import class_row

from app.models.customer import Customer

_COLUMNS = "id, customer_code, full_name, pin_hash, failed_pin_attempts, is_locked"


class CustomerRepository:
    """Reads customers and tracks failed PIN attempts."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def get_by_code(self, customer_code: str) -> Customer | None:
        """Find a customer by their code, like 'C-1001'. None if there's no match."""
        with self.conn.cursor(row_factory=class_row(Customer)) as cur:
            cur.execute(
                f"select {_COLUMNS} from customers where customer_code = %s",
                (customer_code,),
            )
            return cur.fetchone()

    def record_failed_pin(self, customer_id: UUID, max_attempts: int) -> Customer:
        """Add one failed attempt, and lock the customer if they hit the limit.

        Done in a single UPDATE so two calls at the same moment can't both
        slip under the limit.
        """
        with self.conn.cursor(row_factory=class_row(Customer)) as cur:
            cur.execute(
                f"""
                update customers
                   set failed_pin_attempts = failed_pin_attempts + 1,
                       is_locked = is_locked or failed_pin_attempts + 1 >= %s
                 where id = %s
             returning {_COLUMNS}
                """,
                (max_attempts, customer_id),
            )
            customer = cur.fetchone()
        if customer is None:
            raise LookupError(f"customer {customer_id} disappeared")
        return customer

    def reset_failed_pins(self, customer_id: UUID) -> None:
        """Clear the counter after a correct PIN."""
        self.conn.execute(
            "update customers set failed_pin_attempts = 0 where id = %s",
            (customer_id,),
        )
