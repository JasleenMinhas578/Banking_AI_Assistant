"""A row from the accounts table."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Account:
    """A chequing or savings account. Only the last 4 digits are ever stored."""

    id: UUID
    customer_id: UUID
    account_type: str
    last4: str
    balance_cents: int
