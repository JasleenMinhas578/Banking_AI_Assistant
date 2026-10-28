"""Unit tests for request validation."""

import pytest
from pydantic import ValidationError

from app.schemas.session import VerifyRequest


def test_valid_request_is_accepted() -> None:
    body = VerifyRequest(customer_code="C-1001", pin="2468")  # type: ignore[arg-type]

    assert body.pin.get_secret_value() == "2468"


def test_pin_is_hidden_when_printed() -> None:
    body = VerifyRequest(customer_code="C-1001", pin="2468")  # type: ignore[arg-type]

    assert "2468" not in repr(body)
    assert "2468" not in str(body)


@pytest.mark.parametrize("pin", ["123", "12345", "12a4", ""])
def test_pin_must_be_four_digits(pin: str) -> None:
    with pytest.raises(ValidationError):
        VerifyRequest(customer_code="C-1001", pin=pin)  # type: ignore[arg-type]


@pytest.mark.parametrize("code", ["1001", "C1001", "C-10010", "c-1001"])
def test_customer_code_format_is_checked(code: str) -> None:
    with pytest.raises(ValidationError):
        VerifyRequest(customer_code=code, pin="2468")  # type: ignore[arg-type]
