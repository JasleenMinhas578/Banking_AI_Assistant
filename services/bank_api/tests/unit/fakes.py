"""In-memory stand-ins for the repositories, so service rules can be tested
without a database. Each fake has the same methods as the real class."""

from dataclasses import replace
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from app.models.account import Account
from app.models.card import Card
from app.models.customer import Customer
from app.models.dispute import Dispute
from app.models.session import OtpChallenge, Session
from app.models.transaction import Transaction
from app.models.transfer import Transfer


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
        self.otps: dict[UUID, OtpChallenge] = {}

    def create(self, token: str, now: datetime, expires_at: datetime) -> Session:
        session = Session(
            id=uuid4(),
            customer_id=None,
            token=token,
            verified=False,
            step_up_verified=False,
            last_activity_at=now,
            expires_at=expires_at,
        )
        self.by_token[token] = session
        return session

    def get_by_token(self, token: str) -> Session | None:
        return self.by_token.get(token)

    def touch(self, session_id: UUID, now: datetime, expires_at: datetime) -> Session:
        return self._update(session_id, last_activity_at=now, expires_at=expires_at)

    def mark_verified(self, session_id: UUID, customer_id: UUID) -> Session:
        return self._update(session_id, customer_id=customer_id, verified=True)

    def set_otp(self, session_id: UUID, otp_hash: str, expires_at: datetime) -> None:
        self.otps[session_id] = OtpChallenge(otp_hash, expires_at, 0)

    def get_otp(self, session_id: UUID) -> OtpChallenge | None:
        return self.otps.get(session_id)

    def record_otp_failure(self, session_id: UUID) -> int:
        old = self.otps[session_id]
        self.otps[session_id] = replace(old, otp_attempts=old.otp_attempts + 1)
        return old.otp_attempts + 1

    def clear_otp(self, session_id: UUID) -> None:
        self.otps.pop(session_id, None)

    def mark_step_up_verified(self, session_id: UUID) -> Session:
        self.otps.pop(session_id, None)
        return self._update(session_id, step_up_verified=True)

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

    def hash(self, secret: str) -> str:
        return secret


class FakeAccounts:
    def __init__(self, *accounts: Account) -> None:
        self.accounts = list(accounts)

    def list_for_customer(self, customer_id: UUID) -> list[Account]:
        return [a for a in self.accounts if a.customer_id == customer_id]

    def get_for_customer(self, account_id: UUID, customer_id: UUID) -> Account | None:
        return next(
            (a for a in self.accounts if a.id == account_id and a.customer_id == customer_id),
            None,
        )

    def lock_for_customer(self, account_ids: list[UUID], customer_id: UUID) -> dict[UUID, Account]:
        return {
            a.id: a for a in self.accounts if a.id in account_ids and a.customer_id == customer_id
        }

    def add_to_balance(self, account_id: UUID, cents: int) -> None:
        self.accounts = [
            replace(a, balance_cents=a.balance_cents + cents) if a.id == account_id else a
            for a in self.accounts
        ]


class FakeTransactions:
    """owners (optional) maps account_id -> customer_id for ownership checks."""

    def __init__(self, *transactions: Transaction, owners: dict[UUID, UUID] | None = None) -> None:
        self.transactions = list(transactions)
        self.owners = owners or {}
        self.read_accounts: list[UUID] = []

    def list_for_account(self, account_id: UUID, limit: int) -> list[Transaction]:
        self.read_accounts.append(account_id)
        mine = [t for t in self.transactions if t.account_id == account_id]
        return sorted(mine, key=lambda t: t.posted_at, reverse=True)[:limit]

    def get_for_customer(self, transaction_id: UUID, customer_id: UUID) -> Transaction | None:
        return next(
            (
                t
                for t in self.transactions
                if t.id == transaction_id and self.owners.get(t.account_id) == customer_id
            ),
            None,
        )


class FakeDisputes:
    def __init__(self, transactions: FakeTransactions, owners: dict[UUID, UUID]) -> None:
        self.transactions = transactions
        self.owners = owners
        self.by_transaction: dict[UUID, Dispute] = {}

    def create(self, transaction_id: UUID, reason: str) -> bool:
        if transaction_id in self.by_transaction:
            return False
        txn = next(t for t in self.transactions.transactions if t.id == transaction_id)
        self.by_transaction[transaction_id] = Dispute(
            id=uuid4(),
            transaction_id=transaction_id,
            reason=reason,
            status="open",
            created_at=datetime(2026, 10, 28, 12, 0),
            merchant=txn.merchant,
            amount_cents=txn.amount_cents,
        )
        return True

    def get_by_transaction(self, transaction_id: UUID) -> Dispute | None:
        return self.by_transaction.get(transaction_id)

    def list_for_customer(self, customer_id: UUID) -> list[Dispute]:
        txns = {t.id: t for t in self.transactions.transactions}
        return [
            d
            for d in self.by_transaction.values()
            if self.owners.get(txns[d.transaction_id].account_id) == customer_id
        ]


class FakeCards:
    """owners maps each card's account_id to the customer who owns it."""

    def __init__(self, owners: dict[UUID, UUID], *cards: Card) -> None:
        self.owners = owners
        self.by_id = {c.id: c for c in cards}

    def list_for_customer(self, customer_id: UUID) -> list[Card]:
        return [c for c in self.by_id.values() if self.owners[c.account_id] == customer_id]

    def get_for_customer(self, card_id: UUID, customer_id: UUID) -> Card | None:
        card = self.by_id.get(card_id)
        if card is None or self.owners[card.account_id] != customer_id:
            return None
        return card

    def freeze(self, card_id: UUID) -> Card | None:
        card = self.by_id[card_id]
        if card.status != "active":
            return None
        frozen = replace(card, status="frozen", frozen_at=datetime(2026, 10, 28, 12, 0))
        self.by_id[card_id] = frozen
        return frozen


class FakeTransfers:
    """Moves money between FakeAccounts. sent_today is set by tests."""

    def __init__(self, accounts: FakeAccounts) -> None:
        self.accounts = accounts
        self.by_key: dict[str, Transfer] = {}
        self.locked_customers: list[UUID] = []
        self.sent_today = 0
        self.since: datetime | None = None

    def lock_customer(self, customer_id: UUID) -> None:
        self.locked_customers.append(customer_id)

    def get_by_key(self, idempotency_key: str) -> Transfer | None:
        return self.by_key.get(idempotency_key)

    def total_sent_since(self, customer_id: UUID, since: datetime) -> int:
        self.since = since
        return self.sent_today

    def execute(
        self,
        *,
        from_account_id: UUID,
        to_account_id: UUID,
        amount_cents: int,
        idempotency_key: str,
        debit_label: str,
        credit_label: str,
    ) -> Transfer:
        self.accounts.add_to_balance(from_account_id, -amount_cents)
        self.accounts.add_to_balance(to_account_id, amount_cents)
        self.sent_today += amount_cents
        transfer = Transfer(
            uuid4(),
            from_account_id,
            to_account_id,
            amount_cents,
            idempotency_key,
            "completed",
            datetime(2026, 10, 28, 12, 0),
        )
        self.by_key[idempotency_key] = transfer
        return transfer


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now
