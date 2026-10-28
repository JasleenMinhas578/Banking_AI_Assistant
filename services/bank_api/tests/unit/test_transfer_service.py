"""Unit tests for TransferService: every POL-004 rule, at its exact edges."""

from datetime import UTC, datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

from app.core.exceptions import (
    AccountNotFound,
    DailyLimitExceeded,
    IdempotencyKeyReused,
    InsufficientFunds,
    PerTransferLimitExceeded,
    SameAccount,
    StepUpRequired,
    VerificationRequired,
)
from app.models.account import Account
from app.models.session import Session
from app.models.transfer import TransferOutcome
from app.services.transfer_service import TransferLimits, TransferService
from tests.unit.fakes import FakeAccounts, FakeAudit, FakeTransfers

# 01:00 UTC on Oct 28 is still Oct 27 in Newfoundland (UTC-2:30).
NOW = datetime(2026, 10, 28, 1, 0, tzinfo=UTC)
NEWFOUNDLAND = ZoneInfo("America/St_Johns")
PRIYA_ID, MARCUS_ID = uuid4(), uuid4()
CHEQUING = Account(uuid4(), PRIYA_ID, "chequing", "4821", 324_050)
SAVINGS = Account(uuid4(), PRIYA_ID, "savings", "7710", 1_250_000)
MARCUS_CHEQUING = Account(uuid4(), MARCUS_ID, "chequing", "3365", 87_520)
LIMITS = TransferLimits(
    per_transfer_cents=250_000,
    daily_cents=500_000,
    step_up_threshold_cents=100_000,
    timezone=NEWFOUNDLAND,
)

Parts = tuple[TransferService, FakeAccounts, FakeTransfers, FakeAudit]


def make_session(
    customer_id: UUID | None = PRIYA_ID, *, verified: bool = True, step_up: bool = False
) -> Session:
    return Session(uuid4(), customer_id, "tok", verified, step_up, NOW, NOW)


@pytest.fixture
def parts() -> Parts:
    accounts = FakeAccounts(CHEQUING, SAVINGS, MARCUS_CHEQUING)
    transfers, audit = FakeTransfers(accounts), FakeAudit()
    service = TransferService(
        transfers=transfers, accounts=accounts, audit=audit, limits=LIMITS, clock=lambda: NOW
    )
    return service, accounts, transfers, audit


def move(
    service: TransferService,
    cents: int,
    *,
    session: Session | None = None,
    source: Account = CHEQUING,
    target: Account = SAVINGS,
    key: str | None = None,
) -> TransferOutcome:
    return service.transfer(
        session or make_session(),
        from_account_id=source.id,
        to_account_id=target.id,
        amount_cents=cents,
        idempotency_key=key or str(uuid4()),
    )


def balance(accounts: FakeAccounts, account: Account) -> int:
    return next(a.balance_cents for a in accounts.accounts if a.id == account.id)


def test_priya_moves_200_to_savings(parts: Parts) -> None:
    service, accounts, transfers, audit = parts

    outcome = move(service, 20_000)

    assert outcome.created is True
    assert outcome.from_account.balance_cents == 304_050
    assert outcome.to_account.balance_cents == 1_270_000
    assert balance(accounts, CHEQUING) == 304_050
    assert transfers.locked_customers == [PRIYA_ID]
    assert audit.actions() == [("transfer.create", "allowed")]


def test_same_key_twice_moves_money_once(parts: Parts) -> None:
    service, accounts, _, _ = parts

    first = move(service, 20_000, key="key-0001")
    second = move(service, 20_000, key="key-0001")

    assert second.created is False
    assert second.transfer.id == first.transfer.id
    assert balance(accounts, CHEQUING) == 304_050


def test_same_key_for_a_different_transfer_is_refused(parts: Parts) -> None:
    service, _, _, _ = parts
    move(service, 20_000, key="key-0001")

    with pytest.raises(IdempotencyKeyReused):
        move(service, 30_000, key="key-0001")


def test_someone_else_cannot_replay_priyas_key(parts: Parts) -> None:
    service, _, _, _ = parts
    move(service, 20_000, key="key-0001")

    with pytest.raises(IdempotencyKeyReused):
        move(service, 20_000, key="key-0001", session=make_session(MARCUS_ID))


@pytest.mark.parametrize(("cents", "allowed"), [(250_000, True), (250_001, False)])
def test_per_transfer_limit_edges(parts: Parts, cents: int, allowed: bool) -> None:
    service, _, _, _ = parts
    session = make_session(step_up=True)

    if allowed:
        move(service, cents, session=session, source=SAVINGS, target=CHEQUING)
    else:
        with pytest.raises(PerTransferLimitExceeded, match=r"\$2,500\.00"):
            move(service, cents, session=session, source=SAVINGS, target=CHEQUING)


@pytest.mark.parametrize(("cents", "needs_code"), [(100_000, False), (100_001, True)])
def test_one_time_code_needed_only_over_1000(parts: Parts, cents: int, needs_code: bool) -> None:
    service, _, _, _ = parts

    if needs_code:
        with pytest.raises(StepUpRequired):
            move(service, cents)
    else:
        assert move(service, cents).created is True


def test_over_1000_works_after_step_up(parts: Parts) -> None:
    service, _, _, _ = parts

    outcome = move(service, 150_000, session=make_session(step_up=True))

    assert outcome.created is True


def test_cannot_go_below_zero(parts: Parts) -> None:
    service, accounts, _, audit = parts

    stepped_up = make_session(step_up=True)
    move(service, 224_050, session=stepped_up)  # leaves $1,000.00
    with pytest.raises(InsufficientFunds):
        move(service, 100_001, session=stepped_up)

    assert balance(accounts, CHEQUING) == 100_000
    assert audit.rows[-1]["details"]["reason"] == "insufficient_funds"


def test_emptying_the_account_exactly_is_allowed(parts: Parts) -> None:
    service, accounts, _, _ = parts

    move(service, 224_050, session=make_session(step_up=True))
    move(service, 100_000)  # exactly what's left

    assert balance(accounts, CHEQUING) == 0


def test_daily_limit_counts_earlier_transfers(parts: Parts) -> None:
    service, _, transfers, _ = parts
    transfers.sent_today = 450_000

    move(service, 50_000)  # exactly $5,000 in total: allowed
    with pytest.raises(DailyLimitExceeded, match=r"\$0\.00 more today"):
        move(service, 1)


def test_daily_limit_resets_at_midnight_newfoundland_time(parts: Parts) -> None:
    service, _, transfers, _ = parts

    move(service, 1_000)

    assert transfers.since == datetime(2026, 10, 27, 0, 0, tzinfo=NEWFOUNDLAND)


def test_same_account_is_refused(parts: Parts) -> None:
    service, _, _, _ = parts

    with pytest.raises(SameAccount):
        move(service, 1_000, target=CHEQUING)


def test_cannot_send_to_someone_elses_account(parts: Parts) -> None:
    service, accounts, _, _ = parts

    with pytest.raises(AccountNotFound):
        move(service, 1_000, target=MARCUS_CHEQUING)

    assert balance(accounts, MARCUS_CHEQUING) == 87_520


def test_unverified_session_is_refused(parts: Parts) -> None:
    service, _, transfers, _ = parts

    with pytest.raises(VerificationRequired):
        move(service, 1_000, session=make_session(None, verified=False))

    assert transfers.locked_customers == []
