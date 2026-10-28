"""Business rules for viewing accounts."""

from app.models.account import Account
from app.models.session import Session
from app.repositories.account_repository import AccountRepository
from app.repositories.audit_repository import AuditRepository


class AccountService:
    """Lists the verified customer's own accounts, and nobody else's."""

    def __init__(self, *, accounts: AccountRepository, audit: AuditRepository) -> None:
        self.accounts = accounts
        self.audit = audit

    def list_accounts(self, session: Session) -> list[Account]:
        """Return the accounts of whoever verified this session.

        The customer comes from the session, never from the request, so a
        caller can't ask for someone else's accounts.
        """
        customer_id = session.require_customer_id()
        accounts = self.accounts.list_for_customer(customer_id)
        self.audit.record(
            session_id=session.id,
            actor="customer",
            action="accounts.list",
            outcome="allowed",
            details={"count": len(accounts)},
        )
        return accounts
