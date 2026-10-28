"""The code safety net under the detail model: explicit words beat a model's miss."""

import pytest

from app.llm import TransactionsDetails, TransferDetails, fill_from_words, normalize_account
from app.state import Intent, Turn


def said(*texts: str) -> list[Turn]:
    return [{"role": "caller", "text": t} for t in texts]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Checking", "chequing"),
        ("my chequing account", "chequing"),
        ("Savings", "savings"),
        ("saving", "savings"),
        ("visa", None),
        (None, None),
    ],
)
def test_account_names_are_normalized(value: object, expected: str | None) -> None:
    assert normalize_account(value) == expected


def test_model_output_with_checking_is_accepted() -> None:
    details = TransferDetails.model_validate({"from_account": "Checking", "to_account": "SAVINGS"})

    assert (details.from_account, details.to_account) == ("chequing", "savings")


def test_fills_accounts_the_model_missed() -> None:
    """Exactly what qwen2.5:7b returned in the doctor run."""
    missed = TransferDetails(amount="$200")

    fixed = fill_from_words(Intent.TRANSFER, missed, said("move $200 from chequing to savings"))

    assert (fixed.from_account, fixed.to_account, fixed.amount) == ("chequing", "savings", "$200")


def test_explicit_words_beat_a_wrong_model_answer() -> None:
    wrong = TransferDetails(from_account="savings", to_account="chequing", amount="50")

    fixed = fill_from_words(Intent.TRANSFER, wrong, said("put 50 into savings from my checking"))

    assert (fixed.from_account, fixed.to_account) == ("chequing", "savings")


def test_details_from_an_earlier_turn_still_count() -> None:
    conversation = said("I want to move money to savings", "200")

    fixed = fill_from_words(Intent.TRANSFER, TransferDetails(), conversation)

    assert (fixed.to_account, fixed.amount) == ("savings", "200")


def test_nothing_is_invented() -> None:
    fixed = fill_from_words(Intent.TRANSFER, TransferDetails(), said("I want to move money"))

    assert fixed == TransferDetails()


def test_transactions_account_from_a_short_answer() -> None:
    fixed = fill_from_words(Intent.TRANSACTIONS, TransactionsDetails(), said("checking please"))

    assert fixed == TransactionsDetails(account="chequing")
