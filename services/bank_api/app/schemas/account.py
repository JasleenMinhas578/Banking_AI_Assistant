"""Response shapes for accounts."""

from uuid import UUID

from pydantic import BaseModel, Field

from app.core.money import format_cents, mask_last4
from app.models.account import Account


class AccountSummary(BaseModel):
    """One account as the public sees it: masked number, balance in cents."""

    id: UUID
    account_type: str = Field(examples=["chequing"])
    masked_number: str = Field(examples=["••••4821"])
    balance_cents: int = Field(examples=[324050])
    balance: str = Field(examples=["$3,240.50"])

    @classmethod
    def from_account(cls, account: Account) -> "AccountSummary":
        """Build the public view of an account."""
        return cls(
            id=account.id,
            account_type=account.account_type,
            masked_number=mask_last4(account.last4),
            balance_cents=account.balance_cents,
            balance=format_cents(account.balance_cents),
        )


class AccountList(BaseModel):
    """Wrapped in an object (not a bare list) so fields can be added later."""

    accounts: list[AccountSummary]
