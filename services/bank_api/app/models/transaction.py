"""A row from the transactions table."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class Transaction:
    """One purchase or deposit. Negative amounts are money going out."""

    id: UUID
    account_id: UUID
    merchant: str
    amount_cents: int
    status: str
    posted_at: datetime
