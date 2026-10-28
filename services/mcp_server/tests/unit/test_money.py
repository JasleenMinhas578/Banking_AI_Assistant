"""Turning a model's dollar amounts into exact cents."""

import pytest

from app.money import AmountError, format_cents, parse_dollars


@pytest.mark.parametrize(
    ("text", "cents"),
    [("200", 20_000), ("200.5", 20_050), ("$1,250.50", 125_050), (" 0.01 ", 1), ("1e2", 10_000)],
)
def test_parses_dollars_exactly(text: str, cents: int) -> None:
    assert parse_dollars(text) == cents


@pytest.mark.parametrize("text", ["0", "-5", "12.345", "two hundred", "", "NaN", "inf"])
def test_rejects_anything_unclear(text: str) -> None:
    with pytest.raises(AmountError):
        parse_dollars(text)


def test_formats_cents() -> None:
    assert format_cents(125_050) == "$1,250.50"
    assert format_cents(-18_432) == "-$184.32"
