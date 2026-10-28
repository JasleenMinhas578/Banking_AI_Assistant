"""Unit tests for money formatting and masking."""

import pytest

from app.core.money import format_cents, mask_last4


@pytest.mark.parametrize(
    ("cents", "expected"),
    [
        (324050, "$3,240.50"),
        (1250000, "$12,500.00"),
        (5, "$0.05"),
        (0, "$0.00"),
        (-18432, "-$184.32"),
    ],
)
def test_format_cents(cents: int, expected: str) -> None:
    assert format_cents(cents) == expected


def test_mask_shows_only_last_four() -> None:
    assert mask_last4("4821") == "••••4821"
