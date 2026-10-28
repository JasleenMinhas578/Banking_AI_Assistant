"""Request and response shapes for disputes."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.money import format_cents
from app.models.dispute import Dispute

# A fixed list instead of free text: nothing typed by the caller is stored,
# and the reason decides whether a human takes over.
DisputeReason = Literal["fraud", "wrong_amount", "duplicate_charge", "not_received"]


class OpenDisputeRequest(BaseModel):
    """Which charge to dispute, and why."""

    transaction_id: UUID
    reason: DisputeReason = Field(examples=["fraud"])


class DisputeSummary(BaseModel):
    """One dispute as the public sees it."""

    id: UUID
    reference: str = Field(examples=["D-1A2B3C4D"])
    transaction_id: UUID
    merchant: str = Field(examples=["QZ Digital Store Singapore"])
    amount: str = Field(examples=["-$689.99"])
    reason: str
    status: str = Field(examples=["open"])
    created_at: datetime

    @classmethod
    def from_dispute(cls, dispute: Dispute) -> "DisputeSummary":
        """Build the public view of a dispute."""
        return cls(
            id=dispute.id,
            reference=dispute.reference,
            transaction_id=dispute.transaction_id,
            merchant=dispute.merchant,
            amount=format_cents(dispute.amount_cents),
            reason=dispute.reason,
            status=dispute.status,
            created_at=dispute.created_at,
        )


class DisputeList(BaseModel):
    """The caller's disputes."""

    disputes: list[DisputeSummary]


class DisputeResult(BaseModel):
    """What happened, in a sentence the assistant can read out."""

    dispute: DisputeSummary
    created: bool = Field(description="False if a dispute was already open for this charge")
    handoff: bool = Field(description="True if a human agent must take over (fraud)")
    message: str

    @classmethod
    def build(cls, dispute: Dispute, created: bool, handoff: bool) -> "DisputeResult":
        """Describe the outcome of a dispute request."""
        charge = f"the {format_cents(abs(dispute.amount_cents))} charge from {dispute.merchant}"
        if created:
            message = f"Dispute {dispute.reference} is now open for {charge}."
        else:
            message = (
                f"A dispute is already open for {charge}: {dispute.reference}, "
                f"status {dispute.status}."
            )
        if handoff:
            message += " A Puffin Bank agent will follow up."
        return cls(
            dispute=DisputeSummary.from_dispute(dispute),
            created=created,
            handoff=handoff,
            message=message,
        )
