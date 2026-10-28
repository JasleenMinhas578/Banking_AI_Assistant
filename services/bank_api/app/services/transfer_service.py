"""Business rules for transfers, straight from POL-004 (Transfers and limits).

Checks run cheapest first, and every check runs before any money moves:
 1. Verified caller, two different accounts, amount within the per-transfer limit.
 2. Lock the customer, so their transfers run one at a time.
 3. Same Idempotency-Key as an earlier transfer? Return that one, move nothing.
 4. Both accounts belong to the caller.
 5. Over $1,000 needs a one-time code (step-up).
 6. Enough money in the source account (never below $0).
 7. Within the $5,000 daily total (calendar day, Newfoundland time).
Then the money moves in one all-or-nothing database block.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import NoReturn
from uuid import UUID
from zoneinfo import ZoneInfo

from app.core.clock import utc_now
from app.core.exceptions import (
    AccountNotFound,
    BankRefusal,
    DailyLimitExceeded,
    IdempotencyKeyReused,
    InsufficientFunds,
    PerTransferLimitExceeded,
    SameAccount,
    StepUpRequired,
)
from app.core.money import format_cents, mask_last4
from app.models.session import Session
from app.models.transfer import Transfer, TransferOutcome
from app.repositories.account_repository import AccountRepository
from app.repositories.audit_repository import AuditRepository
from app.repositories.transfer_repository import TransferRepository


@dataclass(frozen=True)
class TransferLimits:
    """The POL-004 numbers, in cents. Built from settings in deps.py."""

    per_transfer_cents: int
    daily_cents: int
    step_up_threshold_cents: int
    timezone: ZoneInfo


class TransferService:
    """Moves money between a verified caller's own accounts."""

    def __init__(
        self,
        *,
        transfers: TransferRepository,
        accounts: AccountRepository,
        audit: AuditRepository,
        limits: TransferLimits,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.transfers = transfers
        self.accounts = accounts
        self.audit = audit
        self.limits = limits
        self.clock = clock

    def transfer(
        self,
        session: Session,
        *,
        from_account_id: UUID,
        to_account_id: UUID,
        amount_cents: int,
        idempotency_key: str,
    ) -> TransferOutcome:
        """Run every check, then move the money. Raises a BankRefusal if any check fails."""
        customer_id = session.require_customer_id()
        if from_account_id == to_account_id:
            self._refuse(session, SameAccount(), amount_cents)
        if amount_cents > self.limits.per_transfer_cents:
            limit = format_cents(self.limits.per_transfer_cents)
            self._refuse(
                session,
                PerTransferLimitExceeded(f"The most you can move in one transfer is {limit}."),
                amount_cents,
            )

        self.transfers.lock_customer(customer_id)

        existing = self.transfers.get_by_key(idempotency_key)
        if existing is not None:
            return self._replay(
                session, existing, customer_id, from_account_id, to_account_id, amount_cents
            )

        accounts = self.accounts.lock_for_customer([from_account_id, to_account_id], customer_id)
        source, target = accounts.get(from_account_id), accounts.get(to_account_id)
        if source is None or target is None:
            self._refuse(session, AccountNotFound(), amount_cents)

        if amount_cents > self.limits.step_up_threshold_cents and not session.step_up_verified:
            self._refuse(session, StepUpRequired(), amount_cents)
        if source.balance_cents < amount_cents:
            self._refuse(session, InsufficientFunds(), amount_cents)
        self._check_daily_limit(session, customer_id, amount_cents)

        transfer = self.transfers.execute(
            from_account_id=source.id,
            to_account_id=target.id,
            amount_cents=amount_cents,
            idempotency_key=idempotency_key,
            debit_label=f"Transfer to {target.account_type} {mask_last4(target.last4)}",
            credit_label=f"Transfer from {source.account_type} {mask_last4(source.last4)}",
        )
        self._audit(
            session,
            "allowed",
            reference=transfer.reference,
            amount_cents=amount_cents,
            created=True,
        )
        return TransferOutcome(
            transfer=transfer,
            from_account=replace(source, balance_cents=source.balance_cents - amount_cents),
            to_account=replace(target, balance_cents=target.balance_cents + amount_cents),
            created=True,
        )

    def _replay(
        self,
        session: Session,
        existing: Transfer,
        customer_id: UUID,
        from_account_id: UUID,
        to_account_id: UUID,
        amount_cents: int,
    ) -> TransferOutcome:
        """The same request arrived again: return the first result, move nothing.

        A key reused for a different transfer, or someone else's key, is refused.
        """
        same_request = (
            existing.from_account_id,
            existing.to_account_id,
            existing.amount_cents,
        ) == (from_account_id, to_account_id, amount_cents)
        accounts = self.accounts.lock_for_customer(
            [existing.from_account_id, existing.to_account_id], customer_id
        )
        if not same_request or len(accounts) != 2:
            self._refuse(session, IdempotencyKeyReused(), amount_cents)

        self._audit(
            session,
            "allowed",
            reference=existing.reference,
            amount_cents=amount_cents,
            created=False,
        )
        return TransferOutcome(
            transfer=existing,
            from_account=accounts[existing.from_account_id],
            to_account=accounts[existing.to_account_id],
            created=False,
        )

    def _check_daily_limit(self, session: Session, customer_id: UUID, amount_cents: int) -> None:
        """Refuse if today's transfers plus this one would pass the daily limit."""
        sent_today = self.transfers.total_sent_since(customer_id, self._start_of_today())
        if sent_today + amount_cents > self.limits.daily_cents:
            left = format_cents(max(self.limits.daily_cents - sent_today, 0))
            self._refuse(
                session,
                DailyLimitExceeded(
                    f"This would go over today's limit. You can move up to {left} more today."
                ),
                amount_cents,
            )

    def _start_of_today(self) -> datetime:
        """Midnight at the start of today, in the bank's time zone."""
        local_now = self.clock().astimezone(self.limits.timezone)
        return local_now.replace(hour=0, minute=0, second=0, microsecond=0)

    def _refuse(self, session: Session, error: BankRefusal, amount_cents: int) -> NoReturn:
        """Audit the refusal, then raise it. Nothing has been moved."""
        self._audit(session, "denied", reason=error.code, amount_cents=amount_cents)
        raise error

    def _audit(self, session: Session, outcome: str, **details: object) -> None:
        self.audit.record(
            session_id=session.id,
            actor="customer",
            action="transfer.create",
            outcome=outcome,
            details=details,
        )
