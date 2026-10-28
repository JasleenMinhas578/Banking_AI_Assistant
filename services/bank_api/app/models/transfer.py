"""A row from the transfers table."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.models.account import Account


@dataclass(frozen=True)
class Transfer:
    """Money moved between two of one customer's accounts."""

    id: UUID
    from_account_id: UUID
    to_account_id: UUID
    amount_cents: int
    idempotency_key: str
    status: str
    created_at: datetime

    @property
    def reference(self) -> str:
        """A short reference to read out to the caller, like 'T-1A2B3C4D'."""
        return f"T-{self.id.hex[:8].upper()}"


@dataclass(frozen=True)
class TransferOutcome:
    """A transfer, both accounts as they are now, and whether it just happened."""

    transfer: Transfer
    from_account: Account
    to_account: Account
    created: bool
