"""Unit tests for CardService: freeze your own card, safely, any number of times."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.core.exceptions import CardNotFound, VerificationRequired
from app.models.card import Card
from app.models.session import Session
from app.services.card_service import CardService
from tests.unit.fakes import FakeAudit, FakeCards

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
PRIYA_ID, MARCUS_ID = uuid4(), uuid4()
PRIYA_ACCOUNT, MARCUS_ACCOUNT = uuid4(), uuid4()
PRIYA_CARD = Card(uuid4(), PRIYA_ACCOUNT, "9012", "active", None)
MARCUS_CARD = Card(uuid4(), MARCUS_ACCOUNT, "4417", "active", None)

Parts = tuple[CardService, FakeCards, FakeAudit]


def make_session(customer_id: UUID | None, verified: bool = True) -> Session:
    return Session(uuid4(), customer_id, "tok", verified, False, NOW, NOW)


@pytest.fixture
def parts() -> Parts:
    cards = FakeCards({PRIYA_ACCOUNT: PRIYA_ID, MARCUS_ACCOUNT: MARCUS_ID}, PRIYA_CARD, MARCUS_CARD)
    audit = FakeAudit()
    return CardService(cards=cards, audit=audit), cards, audit


def test_lists_only_the_callers_cards(parts: Parts) -> None:
    service, _, _ = parts

    cards = service.list_cards(make_session(MARCUS_ID))

    assert [c.last4 for c in cards] == ["4417"]


def test_freezing_an_active_card_changes_it(parts: Parts) -> None:
    service, _, audit = parts

    card, changed = service.freeze(make_session(MARCUS_ID), MARCUS_CARD.id)

    assert changed is True
    assert card.status == "frozen"
    assert card.frozen_at is not None
    assert audit.rows[-1]["details"] == {"card_last4": "4417", "changed": True}


def test_freezing_twice_is_safe_and_changes_nothing(parts: Parts) -> None:
    service, _, audit = parts
    service.freeze(make_session(MARCUS_ID), MARCUS_CARD.id)

    card, changed = service.freeze(make_session(MARCUS_ID), MARCUS_CARD.id)

    assert changed is False
    assert card.status == "frozen"
    assert audit.rows[-1]["details"] == {"card_last4": "4417", "changed": False}


def test_cannot_freeze_someone_elses_card(parts: Parts) -> None:
    service, cards, audit = parts

    with pytest.raises(CardNotFound):
        service.freeze(make_session(PRIYA_ID), MARCUS_CARD.id)

    assert cards.by_id[MARCUS_CARD.id].status == "active"
    assert audit.actions() == [("card.freeze", "denied")]


def test_unverified_session_cannot_freeze(parts: Parts) -> None:
    service, _, _ = parts

    with pytest.raises(VerificationRequired):
        service.freeze(make_session(None, verified=False), MARCUS_CARD.id)


def test_the_service_has_no_way_to_unfreeze() -> None:
    assert not any("unfreeze" in name for name in dir(CardService))
