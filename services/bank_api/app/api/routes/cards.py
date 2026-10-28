"""Card routes: list cards and freeze one. There is no unfreeze route on purpose:
unfreezing is human-only, so the safest code for it is no code at all."""

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import CardServiceDep, VerifiedSession
from app.schemas.card import CardList, CardSummary, FreezeResult

router = APIRouter(prefix="/cards", tags=["cards"])

_PROTECTED = {
    401: {"description": "No valid session, or it timed out"},
    403: {"description": "Session not verified with a PIN yet"},
}


@router.get("", responses=_PROTECTED)
def list_cards(session: VerifiedSession, service: CardServiceDep) -> CardList:
    """List the caller's cards with masked numbers and status."""
    return CardList(cards=[CardSummary.from_card(c) for c in service.list_cards(session)])


@router.post(
    "/{card_id}/freeze",
    responses={**_PROTECTED, 404: {"description": "No such card for this customer"}},
)
def freeze_card(card_id: UUID, session: VerifiedSession, service: CardServiceDep) -> FreezeResult:
    """Freeze one of the caller's cards. Safe to repeat."""
    card, changed = service.freeze(session, card_id)
    return FreezeResult.build(card, changed)
