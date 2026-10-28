"""Response shapes for cards."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.money import mask_last4
from app.models.card import Card


class CardSummary(BaseModel):
    """One card as the public sees it."""

    id: UUID
    account_id: UUID
    masked_number: str = Field(examples=["••••4417"])
    status: str = Field(examples=["active"])
    frozen_at: datetime | None

    @classmethod
    def from_card(cls, card: Card) -> "CardSummary":
        """Build the public view of a card."""
        return cls(
            id=card.id,
            account_id=card.account_id,
            masked_number=mask_last4(card.last4),
            status=card.status,
            frozen_at=card.frozen_at,
        )


class CardList(BaseModel):
    """The caller's cards."""

    cards: list[CardSummary]


class FreezeResult(BaseModel):
    """What happened, in a sentence the assistant can read out."""

    card: CardSummary
    changed: bool = Field(description="False if the card was already frozen")
    message: str = Field(examples=["Card ••••4417 is now frozen."])

    @classmethod
    def build(cls, card: Card, changed: bool) -> "FreezeResult":
        """Describe the outcome of a freeze request."""
        masked = mask_last4(card.last4)
        message = (
            f"Card {masked} is now frozen." if changed else f"Card {masked} was already frozen."
        )
        return cls(card=CardSummary.from_card(card), changed=changed, message=message)
