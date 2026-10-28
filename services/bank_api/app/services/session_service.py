"""Business rules for call sessions and PIN verification.

Rules (from the Requirements tab):
- A session starts unverified. Picking a profile does NOT verify anyone.
- 3 wrong PINs lock the customer; only a human can unlock.
- A session times out after 10 minutes without activity.
- The PIN is never stored, logged or returned. Only its hash is compared.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import NoReturn

from app.core.exceptions import (
    AccountLocked,
    InvalidCredentials,
    SessionExpired,
    SessionInvalid,
    VerificationRequired,
)
from app.core.security import PinVerifier, new_session_token
from app.models.customer import Customer
from app.models.session import Session
from app.repositories.audit_repository import AuditRepository
from app.repositories.customer_repository import CustomerRepository
from app.repositories.session_repository import SessionRepository


def utc_now() -> datetime:
    """The current time in UTC. Injected so tests can control the clock."""
    return datetime.now(UTC)


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
        clock: Callable[[], datetime] = utc_now,
        token_factory: Callable[[], str] = new_session_token,
    ) -> None:
        self.sessions = sessions
        self.customers = customers
        self.audit = audit
        self.pins = pins
        self.max_pin_attempts = max_pin_attempts
        self.idle_timeout = idle_timeout
        self.clock = clock
        self.token_factory = token_factory

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
            return session

        customer = self.customers.get_by_code(customer_code)

        if customer is not None and customer.is_locked:
            self._audit(session, "session.verify", "denied",
                        customer_code=customer_code, reason="locked")
            raise AccountLocked()

        # Always run the PIN check, even for an unknown code (see security.py).
        pin_ok = self.pins.check(pin, customer.pin_hash if customer else None)
        if customer is None or not pin_ok:
            self._refuse_wrong_pin(session, customer_code, customer)

        self.customers.reset_failed_pins(customer.id)
        verified = self.sessions.mark_verified(session.id, customer.id)
        self._audit(verified, "session.verify", "allowed", customer_code=customer_code)
        return verified

    def _refuse_wrong_pin(
        self, session: Session, customer_code: str, customer: Customer | None
    ) -> NoReturn:
        """Count the failure, lock on the last strike, and always raise."""
        if customer is None:
            self._audit(session, "session.verify", "denied",
                        customer_code=customer_code, reason="unknown_customer")
            raise InvalidCredentials()

        updated = self.customers.record_failed_pin(customer.id, self.max_pin_attempts)
        self._audit(session, "session.verify", "denied", customer_code=customer_code,
                    reason="wrong_pin", failed_attempts=updated.failed_pin_attempts)

        if updated.is_locked:
            self._audit(session, "customer.lock", "allowed", actor="system",
                        customer_code=customer_code, reason="too_many_wrong_pins",
                        handoff=True)
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
