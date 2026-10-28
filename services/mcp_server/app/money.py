"""Turning what a model says ("200", "$1,250.50") into exact cents, and back."""

from decimal import Decimal, InvalidOperation


class AmountError(ValueError):
    """The amount isn't a clear, positive dollar amount."""


def parse_dollars(text: str) -> int:
    """'$1,250.50' -> 125050. Rejects anything ambiguous instead of guessing.

    Decimal, never float: 0.1 + 0.2 is not 0.3 in floating point, and money
    must be exact.
    """
    cleaned = text.strip().replace("$", "").replace(",", "")
    try:
        amount = Decimal(cleaned)
    except InvalidOperation as exc:
        raise AmountError(f"'{text}' is not an amount in dollars, like 200 or 200.50") from exc
    if not amount.is_finite() or amount <= 0:
        raise AmountError("The amount must be more than $0")
    if amount != amount.quantize(Decimal("0.01")):
        raise AmountError("Amounts can have at most two decimal places")
    return int(amount * 100)


def format_cents(cents: int) -> str:
    """125050 -> '$1,250.50', -18432 -> '-$184.32'."""
    sign = "-" if cents < 0 else ""
    dollars, remainder = divmod(abs(cents), 100)
    return f"{sign}${dollars:,}.{remainder:02d}"
