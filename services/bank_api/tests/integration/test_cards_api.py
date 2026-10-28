"""Cards end to end, with the seeded demo customers."""

from uuid import uuid4

import psycopg
from fastapi.testclient import TestClient

from app.main import app
from tests.integration.helpers import auth, start_session, verified_session


def card_id(client: TestClient, token: str) -> str:
    """The caller's first card ID."""
    return client.get("/cards", headers=auth(token)).json()["cards"][0]["id"]


def test_marcus_sees_his_card_as_active(client: TestClient) -> None:
    token = verified_session(client, "C-1002", "1357")

    cards = client.get("/cards", headers=auth(token)).json()["cards"]

    assert [(c["masked_number"], c["status"]) for c in cards] == [("••••4417", "active")]


def test_marcus_freezes_his_lost_card(client: TestClient, db: psycopg.Connection) -> None:
    token = verified_session(client, "C-1002", "1357")

    response = client.post(f"/cards/{card_id(client, token)}/freeze", headers=auth(token))

    assert response.status_code == 200
    body = response.json()
    assert body["changed"] is True
    assert body["message"] == "Card ••••4417 is now frozen."
    row = db.execute(
        "select status, frozen_at is not null from cards where last4 = '4417'"
    ).fetchone()
    assert row == ("frozen", True)


def test_freezing_twice_is_safe(client: TestClient) -> None:
    token = verified_session(client, "C-1002", "1357")
    card = card_id(client, token)
    first = client.post(f"/cards/{card}/freeze", headers=auth(token)).json()

    second = client.post(f"/cards/{card}/freeze", headers=auth(token))

    assert second.status_code == 200
    assert second.json()["changed"] is False
    assert second.json()["message"] == "Card ••••4417 was already frozen."
    assert second.json()["card"]["frozen_at"] == first["card"]["frozen_at"]


def test_priya_cannot_freeze_marcuss_card(client: TestClient, db: psycopg.Connection) -> None:
    marcus = verified_session(client, "C-1002", "1357")
    marcus_card = card_id(client, marcus)
    priya = verified_session(client, "C-1001", "2468")

    response = client.post(f"/cards/{marcus_card}/freeze", headers=auth(priya))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "card_not_found"
    assert db.execute("select status from cards where last4 = '4417'").fetchone() == ("active",)


def test_made_up_card_is_not_found(client: TestClient) -> None:
    token = verified_session(client, "C-1002", "1357")

    response = client.post(f"/cards/{uuid4()}/freeze", headers=auth(token))

    assert response.status_code == 404


def test_unverified_session_cannot_freeze(client: TestClient) -> None:
    token = start_session(client)

    response = client.post(f"/cards/{uuid4()}/freeze", headers=auth(token))

    assert response.status_code == 403


def test_there_is_no_unfreeze_route(client: TestClient) -> None:
    token = verified_session(client, "C-1002", "1357")

    response = client.post(f"/cards/{card_id(client, token)}/unfreeze", headers=auth(token))

    assert response.status_code == 404
    assert not any("unfreeze" in getattr(route, "path", "") for route in app.routes)


def test_freeze_is_audited(client: TestClient, db: psycopg.Connection) -> None:
    token = verified_session(client, "C-1002", "1357")

    client.post(f"/cards/{card_id(client, token)}/freeze", headers=auth(token))

    row = db.execute(
        "select outcome, details->>'card_last4', details->>'changed' "
        "from audit_log where action = 'card.freeze'"
    ).fetchone()
    assert row == ("allowed", "4417", "true")
