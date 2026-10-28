"""Disputes end to end, with the seeded demo customers."""

import threading
from uuid import uuid4

import psycopg
from fastapi.testclient import TestClient
from httpx import Response

from app.core.config import settings
from app.repositories.dispute_repository import DisputeRepository
from tests.integration.helpers import auth, start_session, verified_session

ELENA, PRIYA = ("C-1003", "8642"), ("C-1001", "2468")


def transaction_id(client: TestClient, token: str, merchant: str) -> str:
    """Find one of the caller's transactions by merchant name."""
    for account in client.get("/accounts", headers=auth(token)).json()["accounts"]:
        url = f"/accounts/{account['id']}/transactions"
        for txn in client.get(url, headers=auth(token)).json()["transactions"]:
            if txn["merchant"] == merchant:
                return txn["id"]
    raise AssertionError(f"no transaction from {merchant}")


def dispute(client: TestClient, token: str, txn_id: str, reason: str = "fraud") -> Response:
    """Open a dispute on a transaction."""
    return client.post(
        "/disputes", headers=auth(token), json={"transaction_id": txn_id, "reason": reason}
    )


def test_elena_disputes_the_suspicious_charge(client: TestClient) -> None:
    token = verified_session(client, *ELENA)
    qz = transaction_id(client, token, "QZ Digital Store Singapore")

    response = dispute(client, token, qz)

    assert response.status_code == 200
    body = response.json()
    assert body["created"] is True
    assert body["handoff"] is True
    assert body["dispute"]["status"] == "open"
    assert body["dispute"]["amount"] == "-$689.99"
    assert body["message"].startswith(f"Dispute {body['dispute']['reference']} is now open")


def test_second_dispute_returns_the_first(client: TestClient, db: psycopg.Connection) -> None:
    token = verified_session(client, *ELENA)
    qz = transaction_id(client, token, "QZ Digital Store Singapore")
    first = dispute(client, token, qz).json()

    second = dispute(client, token, qz, reason="wrong_amount")

    assert second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["dispute"]["reference"] == first["dispute"]["reference"]
    assert db.execute("select count(*) from disputes").fetchone() == (1,)


def test_air_canada_is_outside_the_60_day_window(client: TestClient) -> None:
    token = verified_session(client, *ELENA)
    air_canada = transaction_id(client, token, "Air Canada")

    response = dispute(client, token, air_canada, reason="wrong_amount")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "dispute_window_closed"


def test_pending_amazon_charge_is_refused(client: TestClient) -> None:
    token = verified_session(client, *PRIYA)

    response = dispute(client, token, transaction_id(client, token, "Amazon"))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "transaction_pending"


def test_payroll_deposit_is_refused(client: TestClient) -> None:
    token = verified_session(client, *PRIYA)

    response = dispute(client, token, transaction_id(client, token, "Payroll Deposit"))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "not_a_purchase"


def test_priya_cannot_dispute_elenas_charge(client: TestClient, db: psycopg.Connection) -> None:
    elena = verified_session(client, *ELENA)
    qz = transaction_id(client, elena, "QZ Digital Store Singapore")
    priya = verified_session(client, *PRIYA)

    response = dispute(client, priya, qz)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "transaction_not_found"
    assert db.execute("select count(*) from disputes").fetchone() == (0,)


def test_unknown_reason_is_rejected(client: TestClient) -> None:
    token = verified_session(client, *ELENA)

    response = dispute(client, token, str(uuid4()), reason="i just dont like it")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_unverified_session_gets_403(client: TestClient) -> None:
    token = start_session(client)

    response = dispute(client, token, str(uuid4()))

    assert response.status_code == 403


def test_list_shows_the_new_dispute(client: TestClient) -> None:
    token = verified_session(client, *ELENA)
    dispute(client, token, transaction_id(client, token, "QZ Digital Store Singapore"))

    disputes = client.get("/disputes", headers=auth(token)).json()["disputes"]

    assert [(d["merchant"], d["status"]) for d in disputes] == [
        ("QZ Digital Store Singapore", "open")
    ]


def test_two_disputes_at_the_same_moment_create_only_one(db: psycopg.Connection) -> None:
    """The second insert waits on the first, then 'on conflict do nothing' skips it."""
    row = db.execute(
        "select id from transactions where merchant = 'QZ Digital Store Singapore'"
    ).fetchone()
    assert row is not None
    txn_id = row[0]
    result: dict[str, bool] = {}

    with (
        psycopg.connect(settings.database_url) as first,
        psycopg.connect(settings.database_url) as second,
    ):
        result["first"] = DisputeRepository(first).create(txn_id, "fraud")

        def second_attempt() -> None:
            result["second"] = DisputeRepository(second).create(txn_id, "fraud")
            second.commit()

        thread = threading.Thread(target=second_attempt)
        thread.start()
        thread.join(timeout=0.5)
        assert thread.is_alive(), "the second insert should be waiting for the first"

        first.commit()
        thread.join(timeout=5)

    assert result == {"first": True, "second": False}
    assert db.execute("select count(*) from disputes").fetchone() == (1,)


def test_disputes_are_audited(client: TestClient, db: psycopg.Connection) -> None:
    token = verified_session(client, *ELENA)
    dispute(client, token, transaction_id(client, token, "QZ Digital Store Singapore"))
    dispute(client, token, transaction_id(client, token, "Air Canada"), "wrong_amount")

    rows = db.execute(
        "select outcome from audit_log where action = 'dispute.open' order by id"
    ).fetchall()
    assert rows == [("allowed",), ("denied",)]
