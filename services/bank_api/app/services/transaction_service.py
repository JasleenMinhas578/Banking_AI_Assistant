"""Business rules for viewing transaction history."""

from uuid import UUID

from app.core.exceptions import AccountNotFound
from app.models.account import Account
from app.models.session import Session
from app.models.transaction import Transaction
from app.repositories.account_repository import AccountRepository
from app.repositories.audit_repository import AuditRepository
from app.repositories.transaction_repository import TransactionRepository


class TransactionService:
    """Shows an account's history, only if the caller owns that account."""

    def __init__(
        self,
        *,
        accounts: AccountRepository,
        transactions: TransactionRepository,
        audit: AuditRepository,
    ) -> None:
        self.accounts = accounts
        self.transactions = transactions
        self.audit = audit

    def list_transactions(
        self, session: Session, account_id: UUID, limit: int
    ) -> tuple[Account, list[Transaction]]:
        """Return the account and its latest transactions, newest first.

        The account ID comes from the request, so it can't be trusted: we
        check it belongs to the verified customer before reading anything.
        """
        customer_id = session.require_customer_id()
        account = self.accounts.get_for_customer(account_id, customer_id)
        if account is None:
            self._audit(session, "denied", account_id=str(account_id), reason="not_found")
            raise AccountNotFound()

        transactions = self.transactions.list_for_account(account.id, limit)
        self._audit(session, "allowed", account_id=str(account.id), count=len(transactions))
        return account, transactions

    def _audit(self, session: Session, outcome: str, **details: object) -> None:
        self.audit.record(
            session_id=session.id,
            actor="customer",
            action="transactions.list",
            outcome=outcome,
            details=details,
        )
