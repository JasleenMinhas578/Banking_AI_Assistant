"""Unit tests for AccountService: only your own accounts, only once verified."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.core.exceptions import VerificationRequired
from app.models.account import Account
from app.models.session import Session
from app.services.account_service import AccountService
from tests.unit.fakes import FakeAccounts, FakeAudit

PRIYA_ID, MARCUS_ID = uuid4(), uuid4()
ACCOUNTS = [
    Account(uuid4(), PRIYA_ID, "chequing", "4821", 324050),
    Account(uuid4(), PRIYA_ID, "savings", "7710", 1250000),
    Account(uuid4(), MARCUS_ID, "chequing", "3365", 87520),
]
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


def make_session(customer_id: UUID | None, verified: bool) -> Session:
    return Session(
        id=uuid4(), customer_id=customer_id, token="tok", verified=verified,
        step_up_verified=False, last_activity_at=NOW, expires_at=NOW,
    )


def make_service() -> tuple[AccountService, FakeAudit]:
    audit = FakeAudit()
    return AccountService(accounts=FakeAccounts(*ACCOUNTS), audit=audit), audit


def test_lists_only_the_verified_customers_accounts() -> None:
    service, _ = make_service()

    accounts = service.list_accounts(make_session(PRIYA_ID, verified=True))

    assert [a.last4 for a in accounts] == ["4821", "7710"]


def test_another_customer_never_sees_priyas_accounts() -> None:
    service, _ = make_service()

    accounts = service.list_accounts(make_session(MARCUS_ID, verified=True))

    assert [a.last4 for a in accounts] == ["3365"]


def test_unverified_session_is_refused() -> None:
    service, audit = make_service()

    with pytest.raises(VerificationRequired):
        service.list_accounts(make_session(None, verified=False))

    assert audit.rows == []


def test_listing_is_audited() -> None:
    service, audit = make_service()

    service.list_accounts(make_session(PRIYA_ID, verified=True))

    assert audit.actions() == [("accounts.list", "allowed")]
    assert audit.rows[0]["details"] == {"count": 2}
