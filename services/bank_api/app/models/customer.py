"""A row from the customers table."""

from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True)
class Customer:
    """A bank customer. repr=False keeps the PIN hash out of logs and tracebacks."""

    id: UUID
    customer_code: str
    full_name: str
    pin_hash: str = field(repr=False)
    failed_pin_attempts: int
    is_locked: bool
