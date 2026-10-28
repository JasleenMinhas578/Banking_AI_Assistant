"""GET /accounts end to end, with the seeded demo customers."""

import psycopg
from fastapi.testclient import TestClient

from tests.integration.helpers import auth, start_session, verified_session


def test_unverified_session_gets_403(client: TestClient) -> None:
    token = start_session(client)

    response = client.get("/accounts", headers=auth(token))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "verification_required"


def test_no_token_gets_401(client: TestClient) -> None:
    response = client.get("/accounts")

    assert response.status_code == 401


def test_priya_sees_her_two_accounts_masked(client: TestClient) -> None:
    token = verified_session(client, "C-1001", "2468")

    response = client.get("/accounts", headers=auth(token))

    assert response.status_code == 200
    accounts = response.json()["accounts"]
    summary = [(a["account_type"], a["masked_number"], a["balance_cents"], a["balance"])
               for a in accounts]
    assert summary == [
        ("chequing", "••••4821", 324050, "$3,240.50"),
        ("savings", "••••7710", 1250000, "$12,500.00"),
    ]


def test_each_customer_sees_only_their_own_accounts(client: TestClient) -> None:
    token = verified_session(client, "C-1002", "1357")

    accounts = client.get("/accounts", headers=auth(token)).json()["accounts"]

    assert [a["masked_number"] for a in accounts] == ["••••3365"]


def test_listing_accounts_is_audited(client: TestClient, db: psycopg.Connection) -> None:
    token = verified_session(client, "C-1001", "2468")

    client.get("/accounts", headers=auth(token))

    row = db.execute(
        "select outcome, details->>'count' from audit_log where action = 'accounts.list'"
    ).fetchone()
    assert row == ("allowed", "2")
