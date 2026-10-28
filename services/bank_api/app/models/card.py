"""A row from the cards table."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class Card:
    """A debit card linked to an account. Only the last 4 digits are stored."""

    id: UUID
    account_id: UUID
    last4: str
    status: str
    frozen_at: datetime | None
