"""Business rules for call sessions and PIN verification.

Rules (from the Requirements tab):
- A session starts unverified. Picking a profile does NOT verify anyone.
- 3 wrong PINs lock the customer; only a human can unlock.
- A session times out after 10 minutes without activity.
- The PIN is never stored, logged or returned. Only its hash is compared.
- Transfers over $1,000 also need a one-time code (step-up, POL-004). A code
  lasts 5 minutes and allows 3 tries. Once passed, step-up lasts for the rest
  of the session, which itself ends after 10 idle minutes.
"""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import NoReturn

from app.core.clock import utc_now
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
from app.core.security import PinVerifier, new_one_time_code, new_session_token
from app.models.customer import Customer
from app.models.session import Session
from app.repositories.audit_repository import AuditRepository
from app.repositories.customer_repository import CustomerRepository
from app.repositories.session_repository import SessionRepository


class SessionService:
    """Starts sessions, verifies PINs and enforces the idle timeout."""

    def __init__(
        self,
        *,
        sessions: SessionRepository,
        customers: CustomerRepository,
        audit: AuditRepository,
        pins: PinVerifier,
        max_pin_attempts: int,
        idle_timeout: timedelta,
        otp_ttl: timedelta = timedelta(minutes=5),
        otp_max_attempts: int = 3,
        clock: Callable[[], datetime] = utc_now,
        token_factory: Callable[[], str] = new_session_token,
        code_factory: Callable[[], str] = new_one_time_code,
    ) -> None:
        self.sessions = sessions
        self.customers = customers
        self.audit = audit
        self.pins = pins
        self.max_pin_attempts = max_pin_attempts
        self.idle_timeout = idle_timeout
        self.otp_ttl = otp_ttl
        self.otp_max_attempts = otp_max_attempts
        self.clock = clock
        self.token_factory = token_factory
        self.code_factory = code_factory

    def start(self) -> Session:
        """Open a new, unverified session for an incoming call."""
        now = self.clock()
        session = self.sessions.create(
            self.token_factory(), now=now, expires_at=now + self.idle_timeout
        )
        self._audit(session, "session.start", "allowed")
        return session

    def require_active(self, token: str) -> Session:
        """Return the live session for this token, or refuse.

        Every later endpoint (balances, transfers...) goes through this.
        """
        session = self.sessions.get_by_token(token)
        if session is None:
            raise SessionInvalid()

        now = self.clock()
        if now >= session.expires_at:
            self._audit(session, "session.check", "denied", reason="expired")
            raise SessionExpired()

        return self.sessions.touch(session.id, now=now, expires_at=now + self.idle_timeout)

    def require_verified(self, token: str) -> Session:
        """Like require_active, but the caller must also have passed the PIN check.

        Every banking endpoint (accounts, transfers...) goes through this.
        """
        session = self.require_active(token)
        if not session.verified:
            self._audit(session, "session.check", "denied", reason="not_verified")
            raise VerificationRequired()
        return session

    def verify(self, token: str, customer_code: str, pin: str) -> Session:
        """Check the caller's PIN and, if correct, mark the session verified."""
        session = self.require_active(token)
        if session.verified:
            self._audit(session, "session.verify", "denied", reason="already_verified")
            raise SessionAlreadyVerified()

        customer = self.customers.get_by_code(customer_code)

        if customer is not None and customer.is_locked:
            self._audit(
                session, "session.verify", "denied", customer_code=customer_code, reason="locked"
            )
            raise AccountLocked()

        # Always run the PIN check, even for an unknown code (see security.py).
        pin_ok = self.pins.check(pin, customer.pin_hash if customer else None)
        if customer is None or not pin_ok:
            self._refuse_wrong_pin(session, customer_code, customer)

        self.customers.reset_failed_pins(customer.id)
        verified = self.sessions.mark_verified(session.id, customer.id)
        self._audit(verified, "session.verify", "allowed", customer_code=customer_code)
        return verified

    def start_step_up(self, token: str) -> tuple[str, datetime]:
        """Issue a one-time code for a verified caller (POL-004: transfers over $1,000).

        Returns the plain code and when it expires. Whoever calls this sends
        the code to the customer; only its hash is stored. Asking again
        replaces the old code.
        """
        session = self.require_verified(token)
        code = self.code_factory()
        expires_at = self.clock() + self.otp_ttl
        self.sessions.set_otp(session.id, self.pins.hash(code), expires_at)
        self._audit(session, "step_up.start", "allowed")
        return code, expires_at

    def verify_step_up(self, token: str, code: str) -> Session:
        """Check the one-time code. A wrong code counts; too many cancel it."""
        session = self.require_verified(token)
        challenge = self.sessions.get_otp(session.id)
        if challenge is None or self.clock() >= challenge.otp_expires_at:
            self._audit(session, "step_up.verify", "denied", reason="expired")
            raise OtpExpired()

        if not self.pins.check(code, challenge.otp_hash):
            attempts = self.sessions.record_otp_failure(session.id)
            self._audit(session, "step_up.verify", "denied", reason="wrong_code", attempts=attempts)
            if attempts >= self.otp_max_attempts:
                self.sessions.clear_otp(session.id)
                raise OtpAttemptsExhausted()
            raise InvalidOtp()

        stepped_up = self.sessions.mark_step_up_verified(session.id)
        self._audit(stepped_up, "step_up.verify", "allowed")
        return stepped_up

    def _refuse_wrong_pin(
        self, session: Session, customer_code: str, customer: Customer | None
    ) -> NoReturn:
        """Count the failure, lock on the last strike, and always raise."""
        if customer is None:
            self._audit(
                session,
                "session.verify",
                "denied",
                customer_code=customer_code,
                reason="unknown_customer",
            )
            raise InvalidCredentials()

        updated = self.customers.record_failed_pin(customer.id, self.max_pin_attempts)
        self._audit(
            session,
            "session.verify",
            "denied",
            customer_code=customer_code,
            reason="wrong_pin",
            failed_attempts=updated.failed_pin_attempts,
        )

        if updated.is_locked:
            self._audit(
                session,
                "customer.lock",
                "allowed",
                actor="system",
                customer_code=customer_code,
                reason="too_many_wrong_pins",
                handoff=True,
            )
            raise AccountLocked()
        raise InvalidCredentials()

    def _audit(
        self,
        session: Session,
        action: str,
        outcome: str,
        actor: str = "customer",
        **details: object,
    ) -> None:
        """Write an audit row for this session. Callers never pass the PIN."""
        self.audit.record(
            session_id=session.id,
            actor=actor,
            action=action,
            outcome=outcome,
            details=details,
        )
