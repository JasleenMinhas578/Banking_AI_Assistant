"""Opaque references: short, stable within a conversation, meaningless outside it."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.refs import RefRegistry, UnknownReference

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def test_refs_are_handed_out_in_order_and_stay_the_same() -> None:
    book = RefRegistry(timedelta(minutes=30), Clock()).book_for("tok")
    first, second = uuid4(), uuid4()

    assert [book.ref_for("A", first), book.ref_for("A", second)] == ["A1", "A2"]
    assert book.ref_for("A", first) == "A1"
    assert book.ref_for("T", uuid4()) == "T1"


def test_resolve_accepts_lowercase_and_spaces() -> None:
    book = RefRegistry(timedelta(minutes=30), Clock()).book_for("tok")
    account = uuid4()
    book.ref_for("A", account)

    assert book.resolve("A", " a1 ") == account


def test_a_ref_from_another_kind_or_never_issued_is_refused() -> None:
    book = RefRegistry(timedelta(minutes=30), Clock()).book_for("tok")
    book.ref_for("A", uuid4())

    with pytest.raises(UnknownReference):
        book.resolve("C", "A1")
    with pytest.raises(UnknownReference):
        book.resolve("A", "A2")


def test_each_conversation_has_its_own_refs() -> None:
    registry = RefRegistry(timedelta(minutes=30), Clock())
    priyas_account = uuid4()
    registry.book_for("priya").ref_for("A", priyas_account)

    with pytest.raises(UnknownReference):
        registry.book_for("marcus").resolve("A", "A1")


def test_idle_conversations_are_forgotten() -> None:
    clock = Clock()
    registry = RefRegistry(timedelta(minutes=30), clock)
    registry.book_for("tok").ref_for("A", uuid4())

    clock.now = NOW + timedelta(minutes=31)

    with pytest.raises(UnknownReference):
        registry.book_for("tok").resolve("A", "A1")
