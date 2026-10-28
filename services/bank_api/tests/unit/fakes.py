"""In-memory stand-ins for the repositories, so service rules can be tested
without a database. Each fake has the same methods as the real class."""

from dataclasses import replace
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from app.models.account import Account
from app.models.customer import Customer
from app.models.session import Session


class FakeCustomers:
    def __init__(self, *customers: Customer) -> None:
        self.by_code = {c.customer_code: c for c in customers}

    def get_by_code(self, customer_code: str) -> Customer | None:
        return self.by_code.get(customer_code)

    def record_failed_pin(self, customer_id: UUID, max_attempts: int) -> Customer:
        customer = self._by_id(customer_id)
        attempts = customer.failed_pin_attempts + 1
        updated = replace(
            customer,
            failed_pin_attempts=attempts,
            is_locked=customer.is_locked or attempts >= max_attempts,
        )
        self.by_code[customer.customer_code] = updated
        return updated

    def reset_failed_pins(self, customer_id: UUID) -> None:
        customer = self._by_id(customer_id)
        self.by_code[customer.customer_code] = replace(customer, failed_pin_attempts=0)

    def _by_id(self, customer_id: UUID) -> Customer:
        return next(c for c in self.by_code.values() if c.id == customer_id)


class FakeSessions:
    def __init__(self) -> None:
        self.by_token: dict[str, Session] = {}

    def create(self, token: str, now: datetime, expires_at: datetime) -> Session:
        session = Session(
            id=uuid4(), customer_id=None, token=token, verified=False,
            step_up_verified=False, last_activity_at=now, expires_at=expires_at,
        )
        self.by_token[token] = session
        return session

    def get_by_token(self, token: str) -> Session | None:
        return self.by_token.get(token)

    def touch(self, session_id: UUID, now: datetime, expires_at: datetime) -> Session:
        return self._update(session_id, last_activity_at=now, expires_at=expires_at)

    def mark_verified(self, session_id: UUID, customer_id: UUID) -> Session:
        return self._update(session_id, customer_id=customer_id, verified=True)

    def _update(self, session_id: UUID, **changes: Any) -> Session:
        old = next(s for s in self.by_token.values() if s.id == session_id)
        new = replace(old, **changes)
        self.by_token[old.token] = new
        return new


class FakeAudit:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def record(self, **row: Any) -> None:
        self.rows.append(row)

    def actions(self) -> list[tuple[str, str]]:
        return [(r["action"], r["outcome"]) for r in self.rows]


class FakePins:
    """Treats the 'hash' as the PIN itself, and remembers every check."""

    def __init__(self) -> None:
        self.checked_hashes: list[str | None] = []

    def check(self, pin: str, pin_hash: str | None) -> bool:
        self.checked_hashes.append(pin_hash)
        return pin_hash is not None and pin == pin_hash


class FakeAccounts:
    def __init__(self, *accounts: Account) -> None:
        self.accounts = list(accounts)

    def list_for_customer(self, customer_id: UUID) -> list[Account]:
        return [a for a in self.accounts if a.customer_id == customer_id]


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now
