"""Response shapes for transactions."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.money import format_cents
from app.models.account import Account
from app.models.transaction import Transaction
from app.schemas.account import AccountSummary


class TransactionSummary(BaseModel):
    """One transaction as the public sees it."""

    id: UUID
    merchant: str = Field(examples=["Costco"])
    amount_cents: int = Field(examples=[-18432])
    amount: str = Field(examples=["-$184.32"])
    status: str = Field(examples=["posted"])
    posted_at: datetime

    @classmethod
    def from_transaction(cls, txn: Transaction) -> "TransactionSummary":
        """Build the public view of a transaction."""
        return cls(
            id=txn.id,
            merchant=txn.merchant,
            amount_cents=txn.amount_cents,
            amount=format_cents(txn.amount_cents),
            status=txn.status,
            posted_at=txn.posted_at,
        )


class TransactionList(BaseModel):
    """The account the history belongs to, plus its transactions."""

    account: AccountSummary
    transactions: list[TransactionSummary]

    @classmethod
    def build(cls, account: Account, transactions: list[Transaction]) -> "TransactionList":
        """Combine an account and its transactions into one response."""
        return cls(
            account=AccountSummary.from_account(account),
            transactions=[TransactionSummary.from_transaction(t) for t in transactions],
        )
