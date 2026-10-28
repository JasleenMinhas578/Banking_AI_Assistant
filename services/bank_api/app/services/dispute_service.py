"""Business rules for disputes, straight from POL-003 (Dispute process):

1. A purchase can be disputed within 60 days of its posting date.
2. Pending purchases can't be disputed until they post.
3. One dispute per purchase: asking again returns the existing dispute.
4. Fraud disputes are always passed to a human agent.
"""

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from app.core.clock import utc_now
from app.core.exceptions import (
    DisputeNotAllowed,
    DisputeWindowClosed,
    NotAPurchase,
    TransactionNotFound,
    TransactionPending,
)
from app.models.dispute import Dispute
from app.models.session import Session
from app.models.transaction import Transaction
from app.repositories.audit_repository import AuditRepository
from app.repositories.dispute_repository import DisputeRepository
from app.repositories.transaction_repository import TransactionRepository

# POL-003: "Fraud and stolen-card disputes are always passed to a Puffin Bank agent."
HANDOFF_REASONS = frozenset({"fraud"})


class DisputeService:
    """Opens disputes on the caller's own purchases and lists them."""

    def __init__(
        self,
        *,
        transactions: TransactionRepository,
        disputes: DisputeRepository,
        audit: AuditRepository,
        window: timedelta,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.transactions = transactions
        self.disputes = disputes
        self.audit = audit
        self.window = window
        self.clock = clock

    def list_disputes(self, session: Session) -> list[Dispute]:
        """The verified customer's disputes, newest first."""
        return self.disputes.list_for_customer(session.require_customer_id())

    def open_dispute(
        self, session: Session, transaction_id: UUID, reason: str
    ) -> tuple[Dispute, bool]:
        """Open a dispute, or return the one already open.

        Returns the dispute and whether it was created just now.
        """
        customer_id = session.require_customer_id()
        txn = self.transactions.get_for_customer(transaction_id, customer_id)
        if txn is None:
            self._audit(session, "denied", transaction_id=str(transaction_id), reason="not_found")
            raise TransactionNotFound()

        existing = self.disputes.get_by_transaction(txn.id)
        if existing is not None:
            self._audit(session, "allowed", reference=existing.reference, created=False)
            return existing, False

        self._check_eligible(session, txn)
        created = self.disputes.create(txn.id, reason)
        dispute = self.disputes.get_by_transaction(txn.id)
        if dispute is None:
            raise LookupError(f"dispute for {txn.id} missing right after insert")

        self._audit(
            session,
            "allowed",
            reference=dispute.reference,
            created=created,
            dispute_reason=reason,
            handoff=self.needs_handoff(dispute),
        )
        return dispute, created

    @staticmethod
    def needs_handoff(dispute: Dispute) -> bool:
        """Whether a human agent must take this dispute over."""
        return dispute.reason in HANDOFF_REASONS

    def _check_eligible(self, session: Session, txn: Transaction) -> None:
        """Raise if POL-003 says this transaction can't be disputed."""
        error: DisputeNotAllowed | None = None
        if txn.amount_cents >= 0:
            error = NotAPurchase()
        elif txn.status == "pending":
            error = TransactionPending()
        elif self.clock() - txn.posted_at > self.window:
            error = DisputeWindowClosed(
                f"Purchases can only be disputed within {self.window.days} days of posting."
            )
        if error is not None:
            self._audit(session, "denied", transaction_id=str(txn.id), reason=error.code)
            raise error

    def _audit(self, session: Session, outcome: str, **details: object) -> None:
        self.audit.record(
            session_id=session.id,
            actor="customer",
            action="dispute.open",
            outcome=outcome,
            details=details,
        )
