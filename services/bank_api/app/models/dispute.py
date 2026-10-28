"""A row from the disputes table, joined with the charge it's about."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class Dispute:
    """A challenged charge. merchant and amount_cents come from the transaction."""

    id: UUID
    transaction_id: UUID
    reason: str
    status: str
    created_at: datetime
    merchant: str
    amount_cents: int

    @property
    def reference(self) -> str:
        """A short reference to read out to the caller, like 'D-1A2B3C4D'."""
        return f"D-{self.id.hex[:8].upper()}"
