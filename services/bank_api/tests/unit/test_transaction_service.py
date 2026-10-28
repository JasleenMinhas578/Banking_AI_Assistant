"""Unit tests for TransactionService: the ownership check comes before any read."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.core.exceptions import AccountNotFound, VerificationRequired
from app.models.account import Account
from app.models.session import Session
from app.models.transaction import Transaction
from app.services.transaction_service import TransactionService
from tests.unit.fakes import FakeAccounts, FakeAudit, FakeTransactions

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
PRIYA_ID, MARCUS_ID = uuid4(), uuid4()
PRIYA_CHEQUING = Account(uuid4(), PRIYA_ID, "chequing", "4821", 324050)
MARCUS_CHEQUING = Account(uuid4(), MARCUS_ID, "chequing", "3365", 87520)


def txn(merchant: str, cents: int, days_ago: int, account: Account = PRIYA_CHEQUING) -> Transaction:
    return Transaction(
        uuid4(), account.id, merchant, cents, "posted", NOW - timedelta(days=days_ago)
    )


TRANSACTIONS = [
    txn("Costco", -18432, 2),
    txn("Tim Hortons", -645, 1),
    txn("Payroll Deposit", 245000, 5),
    txn("Sobeys", -9214, 1, MARCUS_CHEQUING),
]


def make_session(customer_id: UUID | None, verified: bool = True) -> Session:
    return Session(uuid4(), customer_id, "tok", verified, False, NOW, NOW)


Parts = tuple[TransactionService, FakeTransactions, FakeAudit]


@pytest.fixture
def parts() -> Parts:
    transactions, audit = FakeTransactions(*TRANSACTIONS), FakeAudit()
    service = TransactionService(
        accounts=FakeAccounts(PRIYA_CHEQUING, MARCUS_CHEQUING),
        transactions=transactions,
        audit=audit,
    )
    return service, transactions, audit


def test_owner_gets_transactions_newest_first(parts: Parts) -> None:
    service, _, _ = parts

    account, transactions = service.list_transactions(
        make_session(PRIYA_ID), PRIYA_CHEQUING.id, limit=20
    )

    assert account == PRIYA_CHEQUING
    assert [t.merchant for t in transactions] == ["Tim Hortons", "Costco", "Payroll Deposit"]


def test_limit_is_respected(parts: Parts) -> None:
    service, _, _ = parts

    _, transactions = service.list_transactions(make_session(PRIYA_ID), PRIYA_CHEQUING.id, limit=1)

    assert len(transactions) == 1


def test_someone_elses_account_is_not_found_and_never_read(parts: Parts) -> None:
    service, transactions, audit = parts

    with pytest.raises(AccountNotFound):
        service.list_transactions(make_session(MARCUS_ID), PRIYA_CHEQUING.id, limit=20)

    assert transactions.read_accounts == []  # refused before touching the history
    assert audit.actions() == [("transactions.list", "denied")]


def test_unknown_account_is_not_found(parts: Parts) -> None:
    service, _, _ = parts

    with pytest.raises(AccountNotFound):
        service.list_transactions(make_session(PRIYA_ID), uuid4(), limit=20)


def test_unverified_session_is_refused(parts: Parts) -> None:
    service, _, _ = parts

    with pytest.raises(VerificationRequired):
        service.list_transactions(make_session(None, verified=False), PRIYA_CHEQUING.id, 20)
