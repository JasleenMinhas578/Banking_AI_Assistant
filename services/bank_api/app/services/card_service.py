"""Business rules for cards.

- Freezing is instant and safe to repeat (idempotent).
- Unfreezing is human-only, so this service has no way to do it.
"""

from uuid import UUID

from app.core.exceptions import CardNotFound
from app.models.card import Card
from app.models.session import Session
from app.repositories.audit_repository import AuditRepository
from app.repositories.card_repository import CardRepository


class CardService:
    """Lists the caller's cards and freezes them on request."""

    def __init__(self, *, cards: CardRepository, audit: AuditRepository) -> None:
        self.cards = cards
        self.audit = audit

    def list_cards(self, session: Session) -> list[Card]:
        """The verified customer's own cards."""
        cards = self.cards.list_for_customer(session.require_customer_id())
        self._audit(session, "card.list", "allowed", count=len(cards))
        return cards

    def freeze(self, session: Session, card_id: UUID) -> tuple[Card, bool]:
        """Freeze one of the caller's cards.

        Returns the card and whether anything changed. Freezing a card that
        is already frozen is not an error: the result is the same either way.
        """
        customer_id = session.require_customer_id()
        card = self.cards.get_for_customer(card_id, customer_id)
        if card is None:
            self._audit(session, "card.freeze", "denied", card_id=str(card_id), reason="not_found")
            raise CardNotFound()

        frozen = self.cards.freeze(card.id)
        if frozen is None:
            # Already frozen, perhaps by a repeat of this same request.
            self._audit(session, "card.freeze", "allowed", card_last4=card.last4, changed=False)
            return card, False

        self._audit(session, "card.freeze", "allowed", card_last4=card.last4, changed=True)
        return frozen, True

    def _audit(self, session: Session, action: str, outcome: str, **details: object) -> None:
        self.audit.record(
            session_id=session.id,
            actor="customer",
            action=action,
            outcome=outcome,
            details=details,
        )
