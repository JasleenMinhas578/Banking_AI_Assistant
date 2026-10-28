"""Unit tests for SessionService: the rules, with no database involved."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from app.core.exceptions import (
    AccountLocked,
    InvalidCredentials,
    InvalidOtp,
    OtpAttemptsExhausted,
    OtpExpired,
    SessionAlreadyVerified,
    SessionExpired,
    SessionInvalid,
    VerificationRequired,
)
from app.models.customer import Customer
from app.services.session_service import SessionService
from tests.unit.fakes import FakeAudit, FakeClock, FakeCustomers, FakePins, FakeSessions

START = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
PRIYA = Customer(
    id=uuid4(),
    customer_code="C-1001",
    full_name="Priya Sharma",
    pin_hash="2468",
    failed_pin_attempts=0,
    is_locked=False,
)


@pytest.fixture
def env() -> dict[str, Any]:
    """A fresh service plus handles on its fakes."""
    fakes: dict[str, Any] = {
        "customers": FakeCustomers(PRIYA),
        "sessions": FakeSessions(),
        "audit": FakeAudit(),
        "pins": FakePins(),
        "clock": FakeClock(START),
    }
    fakes["service"] = SessionService(
        sessions=fakes["sessions"],
        customers=fakes["customers"],
        audit=fakes["audit"],
        pins=fakes["pins"],
        max_pin_attempts=3,
        idle_timeout=timedelta(minutes=10),
        clock=fakes["clock"],
        token_factory=lambda: "tok-123",
        code_factory=lambda: "123456",
        otp_ttl=timedelta(minutes=5),
        otp_max_attempts=3,
    )
    return fakes


def test_new_session_is_unverified_and_expires_in_ten_minutes(env: dict[str, Any]) -> None:
    session = env["service"].start()

    assert session.verified is False
    assert session.customer_id is None
    assert session.expires_at == START + timedelta(minutes=10)
    assert env["audit"].actions() == [("session.start", "allowed")]


def test_correct_pin_verifies_the_session(env: dict[str, Any]) -> None:
    env["service"].start()

    session = env["service"].verify("tok-123", "C-1001", "2468")

    assert session.verified is True
    assert session.customer_id == PRIYA.id
    assert ("session.verify", "allowed") in env["audit"].actions()


def test_wrong_pin_is_refused_and_counted(env: dict[str, Any]) -> None:
    env["service"].start()

    with pytest.raises(InvalidCredentials):
        env["service"].verify("tok-123", "C-1001", "0000")

    assert env["customers"].get_by_code("C-1001").failed_pin_attempts == 1
    assert env["sessions"].get_by_token("tok-123").verified is False


def test_third_wrong_pin_locks_the_customer(env: dict[str, Any]) -> None:
    env["service"].start()
    for _ in range(2):
        with pytest.raises(InvalidCredentials):
            env["service"].verify("tok-123", "C-1001", "0000")

    with pytest.raises(AccountLocked):
        env["service"].verify("tok-123", "C-1001", "0000")

    assert env["customers"].get_by_code("C-1001").is_locked is True
    assert ("customer.lock", "allowed") in env["audit"].actions()


def test_locked_customer_is_refused_even_with_the_right_pin(env: dict[str, Any]) -> None:
    env["service"].start()
    for _ in range(3):
        with pytest.raises((InvalidCredentials, AccountLocked)):
            env["service"].verify("tok-123", "C-1001", "0000")

    with pytest.raises(AccountLocked):
        env["service"].verify("tok-123", "C-1001", "2468")


def test_correct_pin_resets_the_failure_counter(env: dict[str, Any]) -> None:
    env["service"].start()
    with pytest.raises(InvalidCredentials):
        env["service"].verify("tok-123", "C-1001", "0000")

    env["service"].verify("tok-123", "C-1001", "2468")

    assert env["customers"].get_by_code("C-1001").failed_pin_attempts == 0


def test_unknown_customer_gets_the_same_error_and_still_runs_a_pin_check(
    env: dict[str, Any],
) -> None:
    env["service"].start()

    with pytest.raises(InvalidCredentials):
        env["service"].verify("tok-123", "C-9999", "1234")

    # The check ran against "no hash", so timing doesn't reveal the code is fake.
    assert env["pins"].checked_hashes == [None]


def test_unknown_token_is_refused(env: dict[str, Any]) -> None:
    with pytest.raises(SessionInvalid):
        env["service"].require_active("not-a-real-token")


def test_session_expires_after_ten_idle_minutes(env: dict[str, Any]) -> None:
    env["service"].start()
    env["clock"].now = START + timedelta(minutes=10)

    with pytest.raises(SessionExpired):
        env["service"].require_active("tok-123")


def test_activity_pushes_the_timeout_back(env: dict[str, Any]) -> None:
    env["service"].start()
    env["clock"].now = START + timedelta(minutes=9)
    env["service"].require_active("tok-123")

    env["clock"].now = START + timedelta(minutes=18)
    session = env["service"].require_active("tok-123")

    assert session.expires_at == START + timedelta(minutes=28)


def test_pin_never_appears_in_the_audit_log(env: dict[str, Any]) -> None:
    env["service"].start()
    with pytest.raises(InvalidCredentials):
        env["service"].verify("tok-123", "C-1001", "1111")
    env["service"].verify("tok-123", "C-1001", "2468")

    audit_text = repr([row["details"] for row in env["audit"].rows])
    assert "1111" not in audit_text
    assert "2468" not in audit_text


def test_unverified_session_cannot_pass_the_verified_gate(env: dict[str, Any]) -> None:
    env["service"].start()

    with pytest.raises(VerificationRequired):
        env["service"].require_verified("tok-123")

    assert ("session.check", "denied") in env["audit"].actions()


def test_verified_session_passes_the_verified_gate(env: dict[str, Any]) -> None:
    env["service"].start()
    env["service"].verify("tok-123", "C-1001", "2468")

    session = env["service"].require_verified("tok-123")

    assert session.customer_id == PRIYA.id


def test_verifying_twice_is_refused_even_with_the_right_pin(env: dict[str, Any]) -> None:
    env["service"].start()
    env["service"].verify("tok-123", "C-1001", "2468")

    with pytest.raises(SessionAlreadyVerified):
        env["service"].verify("tok-123", "C-1001", "2468")


def test_wrong_pin_on_a_verified_session_never_succeeds(env: dict[str, Any]) -> None:
    env["service"].start()
    env["service"].verify("tok-123", "C-1001", "2468")

    with pytest.raises(SessionAlreadyVerified):
        env["service"].verify("tok-123", "C-1001", "0000")


def verified(env: dict[str, Any]) -> None:
    env["service"].start()
    env["service"].verify("tok-123", "C-1001", "2468")


def test_step_up_needs_a_verified_session_first(env: dict[str, Any]) -> None:
    env["service"].start()

    with pytest.raises(VerificationRequired):
        env["service"].start_step_up("tok-123")


def test_right_code_steps_up_the_session(env: dict[str, Any]) -> None:
    verified(env)
    code, expires_at = env["service"].start_step_up("tok-123")

    session = env["service"].verify_step_up("tok-123", code)

    assert session.step_up_verified is True
    assert expires_at == START + timedelta(minutes=5)
    assert env["sessions"].otps == {}  # the code is used up


def test_wrong_code_is_refused_and_counted(env: dict[str, Any]) -> None:
    verified(env)
    env["service"].start_step_up("tok-123")

    with pytest.raises(InvalidOtp):
        env["service"].verify_step_up("tok-123", "000000")

    session_id = env["sessions"].get_by_token("tok-123").id
    assert env["sessions"].otps[session_id].otp_attempts == 1


def test_third_wrong_code_cancels_it(env: dict[str, Any]) -> None:
    verified(env)
    env["service"].start_step_up("tok-123")
    for _ in range(2):
        with pytest.raises(InvalidOtp):
            env["service"].verify_step_up("tok-123", "000000")

    with pytest.raises(OtpAttemptsExhausted):
        env["service"].verify_step_up("tok-123", "000000")
    with pytest.raises(OtpExpired):  # even the right code is now useless
        env["service"].verify_step_up("tok-123", "123456")


def test_code_expires_after_five_minutes(env: dict[str, Any]) -> None:
    verified(env)
    env["service"].start_step_up("tok-123")
    env["clock"].now = START + timedelta(minutes=5)

    with pytest.raises(OtpExpired):
        env["service"].verify_step_up("tok-123", "123456")


def test_code_cannot_be_used_twice(env: dict[str, Any]) -> None:
    verified(env)
    env["service"].start_step_up("tok-123")
    env["service"].verify_step_up("tok-123", "123456")

    with pytest.raises(OtpExpired):
        env["service"].verify_step_up("tok-123", "123456")


def test_code_never_appears_in_the_audit_log(env: dict[str, Any]) -> None:
    verified(env)
    env["service"].start_step_up("tok-123")
    with pytest.raises(InvalidOtp):
        env["service"].verify_step_up("tok-123", "999999")
    env["service"].verify_step_up("tok-123", "123456")

    audit_text = repr([row["details"] for row in env["audit"].rows])
    assert "123456" not in audit_text
    assert "999999" not in audit_text
