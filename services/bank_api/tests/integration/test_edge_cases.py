"""Sad paths that are easy to forget: odd headers, double verification,
simultaneous requests, and crashes halfway through a request."""

import threading
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.repositories.customer_repository import CustomerRepository
from app.services.account_service import AccountService
from tests.integration.helpers import verified_session


def test_wrong_auth_scheme_is_refused(client: TestClient) -> None:
    response = client.get("/sessions/me", headers={"Authorization": "Basic abc123"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "session_invalid"


def test_verifying_twice_is_refused_even_with_a_wrong_pin(client: TestClient) -> None:
    token = verified_session(client, "C-1001", "2468")

    response = client.post(
        "/sessions/verify",
        headers={"Authorization": f"Bearer {token}"},
        json={"customer_code": "C-1001", "pin": "0000"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "already_verified"


def test_two_wrong_pins_at_the_same_moment_are_both_counted(db: psycopg.Connection) -> None:
    """The second update must wait for the first, then add to its result."""
    row = db.execute("select id from customers where customer_code = 'C-1001'").fetchone()
    assert row is not None
    customer_id = row[0]
    result: dict[str, Any] = {}

    with (
        psycopg.connect(settings.database_url) as first,
        psycopg.connect(settings.database_url) as second,
    ):
        CustomerRepository(first).record_failed_pin(customer_id, 3)  # holds the row lock

        def second_attempt() -> None:
            result["customer"] = CustomerRepository(second).record_failed_pin(customer_id, 3)
            second.commit()

        thread = threading.Thread(target=second_attempt)
        thread.start()
        thread.join(timeout=0.5)
        assert thread.is_alive(), "the second update should be waiting for the lock"

        first.commit()
        thread.join(timeout=5)

    assert result["customer"].failed_pin_attempts == 2


def test_a_crash_rolls_back_everything_the_request_wrote(
    db: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refusals are saved, but an unexpected crash must leave no trace.
    This is what will keep a half-finished transfer from ever being saved."""
    original = AccountService.list_accounts

    def write_then_crash(self: AccountService, session: Any) -> Any:
        original(self, session)  # writes the audit row
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(AccountService, "list_accounts", write_then_crash)

    with TestClient(app, raise_server_exceptions=False) as crashing_client:
        token = verified_session(crashing_client, "C-1001", "2468")
        response = crashing_client.get("/accounts", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 500
    count = db.execute("select count(*) from audit_log where action = 'accounts.list'").fetchone()
    assert count == (0,)
