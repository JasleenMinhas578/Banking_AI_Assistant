"""Unit tests for DisputeService: every POL-003 rule, with a fixed clock."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.core.exceptions import (
    DisputeWindowClosed,
    NotAPurchase,
    TransactionNotFound,
    TransactionPending,
    VerificationRequired,
)
from app.models.session import Session
from app.models.transaction import Transaction
from app.services.dispute_service import DisputeService
from tests.unit.fakes import FakeAudit, FakeDisputes, FakeTransactions

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
ELENA_ID, PRIYA_ID = uuid4(), uuid4()
ELENA_ACCOUNT, PRIYA_ACCOUNT = uuid4(), uuid4()
OWNERS = {ELENA_ACCOUNT: ELENA_ID, PRIYA_ACCOUNT: PRIYA_ID}


def txn(
    merchant: str,
    cents: int,
    days_ago: float,
    status: str = "posted",
    account: UUID = ELENA_ACCOUNT,
) -> Transaction:
    return Transaction(uuid4(), account, merchant, cents, status, NOW - timedelta(days=days_ago))


QZ = txn("QZ Digital Store Singapore", -68999, 4)
AIR_CANADA = txn("Air Canada", -54300, 75)
EXACTLY_60_DAYS = txn("Exactly 60 days", -1000, 60)
JUST_OVER_60 = txn("Just over 60 days", -1000, 60.01)
PENDING = txn("Amazon", -5999, 0, status="pending")
DEPOSIT = txn("Payroll Deposit", 245000, 5)
PRIYAS_COSTCO = txn("Costco", -18432, 2, account=PRIYA_ACCOUNT)

Parts = tuple[DisputeService, FakeDisputes, FakeAudit]


def make_session(customer_id: UUID | None = ELENA_ID, verified: bool = True) -> Session:
    return Session(uuid4(), customer_id, "tok", verified, False, NOW, NOW)


@pytest.fixture
def parts() -> Parts:
    transactions = FakeTransactions(
        QZ,
        AIR_CANADA,
        EXACTLY_60_DAYS,
        JUST_OVER_60,
        PENDING,
        DEPOSIT,
        PRIYAS_COSTCO,
        owners=OWNERS,
    )
    disputes, audit = FakeDisputes(transactions, OWNERS), FakeAudit()
    service = DisputeService(
        transactions=transactions,
        disputes=disputes,
        audit=audit,
        window=timedelta(days=60),
        clock=lambda: NOW,
    )
    return service, disputes, audit


def test_elena_disputes_the_suspicious_charge(parts: Parts) -> None:
    service, _, _ = parts

    dispute, created = service.open_dispute(make_session(), QZ.id, "fraud")

    assert created is True
    assert (dispute.merchant, dispute.status, dispute.reason) == (
        "QZ Digital Store Singapore",
        "open",
        "fraud",
    )
    assert dispute.reference.startswith("D-") and len(dispute.reference) == 10


def test_disputing_again_returns_the_existing_dispute(parts: Parts) -> None:
    service, disputes, _ = parts
    first, _ = service.open_dispute(make_session(), QZ.id, "fraud")

    second, created = service.open_dispute(make_session(), QZ.id, "wrong_amount")

    assert created is False
    assert second.id == first.id
    assert second.reason == "fraud"  # the original is kept, not overwritten
    assert len(disputes.by_transaction) == 1


def test_fraud_needs_a_human_but_other_reasons_dont(parts: Parts) -> None:
    service, _, _ = parts

    fraud, _ = service.open_dispute(make_session(), QZ.id, "fraud")
    other, _ = service.open_dispute(make_session(), EXACTLY_60_DAYS.id, "wrong_amount")

    assert service.needs_handoff(fraud) is True
    assert service.needs_handoff(other) is False


def test_charge_older_than_60_days_is_refused(parts: Parts) -> None:
    service, disputes, audit = parts

    with pytest.raises(DisputeWindowClosed, match="60 days"):
        service.open_dispute(make_session(), AIR_CANADA.id, "wrong_amount")

    assert disputes.by_transaction == {}
    assert audit.rows[-1]["details"]["reason"] == "dispute_window_closed"


def test_window_edges(parts: Parts) -> None:
    service, _, _ = parts

    _, created = service.open_dispute(make_session(), EXACTLY_60_DAYS.id, "wrong_amount")
    assert created is True
    with pytest.raises(DisputeWindowClosed):
        service.open_dispute(make_session(), JUST_OVER_60.id, "wrong_amount")


def test_pending_charge_is_refused(parts: Parts) -> None:
    service, _, _ = parts

    with pytest.raises(TransactionPending):
        service.open_dispute(make_session(), PENDING.id, "not_received")


def test_deposit_is_refused(parts: Parts) -> None:
    service, _, _ = parts

    with pytest.raises(NotAPurchase):
        service.open_dispute(make_session(), DEPOSIT.id, "wrong_amount")


def test_someone_elses_transaction_is_not_found(parts: Parts) -> None:
    service, _, _ = parts

    with pytest.raises(TransactionNotFound):
        service.open_dispute(make_session(ELENA_ID), PRIYAS_COSTCO.id, "fraud")


def test_unverified_session_is_refused(parts: Parts) -> None:
    service, _, _ = parts

    with pytest.raises(VerificationRequired):
        service.open_dispute(make_session(None, verified=False), QZ.id, "fraud")


def test_list_shows_only_the_callers_disputes(parts: Parts) -> None:
    service, _, _ = parts
    service.open_dispute(make_session(ELENA_ID), QZ.id, "fraud")
    service.open_dispute(make_session(PRIYA_ID), PRIYAS_COSTCO.id, "wrong_amount")

    elenas = service.list_disputes(make_session(ELENA_ID))

    assert [d.merchant for d in elenas] == ["QZ Digital Store Singapore"]
