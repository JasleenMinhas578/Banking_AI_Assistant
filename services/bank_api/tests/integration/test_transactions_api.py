"""GET /accounts/{id}/transactions end to end, with the seeded demo customers."""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.integration.helpers import auth, start_session, verified_session


def account_id(client: TestClient, token: str, last4: str) -> str:
    """Look up one of the caller's account IDs by its last 4 digits."""
    accounts = client.get("/accounts", headers=auth(token)).json()["accounts"]
    return next(a["id"] for a in accounts if a["masked_number"].endswith(last4))


def test_priya_sees_her_chequing_history_newest_first(client: TestClient) -> None:
    token = verified_session(client, "C-1001", "2468")
    chequing = account_id(client, token, "4821")

    response = client.get(f"/accounts/{chequing}/transactions", headers=auth(token))

    assert response.status_code == 200
    body = response.json()
    assert body["account"]["masked_number"] == "••••4821"
    rows = [(t["merchant"], t["amount"], t["status"]) for t in body["transactions"]]
    assert rows == [
        ("Amazon", "-$59.99", "pending"),
        ("Tim Hortons", "-$6.45", "posted"),
        ("Costco", "-$184.32", "posted"),
        ("Payroll Deposit", "$2,450.00", "posted"),
    ]


def test_limit_returns_only_the_newest(client: TestClient) -> None:
    token = verified_session(client, "C-1001", "2468")
    chequing = account_id(client, token, "4821")

    response = client.get(f"/accounts/{chequing}/transactions?limit=2", headers=auth(token))

    assert [t["merchant"] for t in response.json()["transactions"]] == ["Amazon", "Tim Hortons"]


def test_limit_over_the_maximum_is_rejected(client: TestClient) -> None:
    token = verified_session(client, "C-1001", "2468")
    chequing = account_id(client, token, "4821")

    response = client.get(f"/accounts/{chequing}/transactions?limit=101", headers=auth(token))

    assert response.status_code == 422


def test_marcus_cannot_read_priyas_account(client: TestClient) -> None:
    priya = verified_session(client, "C-1001", "2468")
    priyas_chequing = account_id(client, priya, "4821")
    marcus = verified_session(client, "C-1002", "1357")

    response = client.get(f"/accounts/{priyas_chequing}/transactions", headers=auth(marcus))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "account_not_found"
    assert "Costco" not in response.text


def test_made_up_account_id_is_not_found(client: TestClient) -> None:
    token = verified_session(client, "C-1001", "2468")

    response = client.get(f"/accounts/{uuid4()}/transactions", headers=auth(token))

    assert response.status_code == 404


def test_account_id_that_isnt_a_uuid_is_rejected(client: TestClient) -> None:
    token = verified_session(client, "C-1001", "2468")

    response = client.get("/accounts/not-an-id/transactions", headers=auth(token))

    assert response.status_code == 422


def test_unverified_session_gets_403(client: TestClient) -> None:
    token = start_session(client)

    response = client.get(f"/accounts/{uuid4()}/transactions", headers=auth(token))

    assert response.status_code == 403
