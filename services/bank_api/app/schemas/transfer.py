"""Request and response shapes for transfers."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.money import format_cents, mask_last4
from app.models.transfer import TransferOutcome
from app.schemas.account import AccountSummary


class TransferRequest(BaseModel):
    """Move money between two of your own accounts. Amounts are whole cents."""

    from_account_id: UUID
    to_account_id: UUID
    amount_cents: int = Field(gt=0, examples=[20000], description="20000 = $200.00")


class TransferSummary(BaseModel):
    """One completed transfer."""

    id: UUID
    reference: str = Field(examples=["T-1A2B3C4D"])
    amount_cents: int
    amount: str = Field(examples=["$200.00"])
    created_at: datetime


class TransferResult(BaseModel):
    """What happened, with both balances afterwards and a sentence to read out."""

    transfer: TransferSummary
    from_account: AccountSummary
    to_account: AccountSummary
    created: bool = Field(description="False if this was a repeat of an earlier request")
    message: str

    @classmethod
    def from_outcome(cls, outcome: TransferOutcome) -> "TransferResult":
        """Describe the outcome of a transfer request."""
        transfer, source, target = outcome.transfer, outcome.from_account, outcome.to_account
        amount = format_cents(transfer.amount_cents)
        move = (
            f"{amount} from {source.account_type} {mask_last4(source.last4)} "
            f"to {target.account_type} {mask_last4(target.last4)}"
        )
        message = (
            f"Moved {move}. Reference {transfer.reference}."
            if outcome.created
            else f"This transfer was already done: {move}, reference {transfer.reference}."
        )
        return cls(
            transfer=TransferSummary(
                id=transfer.id,
                reference=transfer.reference,
                amount_cents=transfer.amount_cents,
                amount=amount,
                created_at=transfer.created_at,
            ),
            from_account=AccountSummary.from_account(source),
            to_account=AccountSummary.from_account(target),
            created=outcome.created,
            message=message,
        )
