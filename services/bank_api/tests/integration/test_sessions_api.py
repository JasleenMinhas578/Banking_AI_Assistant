"""Sessions and PIN verification, end to end through HTTP and the database."""

import psycopg
from fastapi.testclient import TestClient

PRIYA = {"customer_code": "C-1001", "pin": "2468"}


def start_session(client: TestClient) -> str:
    response = client.post("/sessions")
    assert response.status_code == 201
    return response.json()["session_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def verify(client: TestClient, token: str, code: str, pin: str) -> int:
    response = client.post(
        "/sessions/verify", headers=auth(token), json={"customer_code": code, "pin": pin}
    )
    return response.status_code


def test_new_session_starts_unverified(client: TestClient) -> None:
    token = start_session(client)

    response = client.get("/sessions/me", headers=auth(token))

    assert response.status_code == 200
    assert response.json()["verified"] is False


def test_correct_pin_verifies_the_session(client: TestClient) -> None:
    token = start_session(client)

    response = client.post("/sessions/verify", headers=auth(token), json=PRIYA)

    assert response.status_code == 200
    assert response.json()["verified"] is True
    assert client.get("/sessions/me", headers=auth(token)).json()["verified"] is True


def test_wrong_pin_is_refused_and_the_failure_is_saved(
    client: TestClient, db: psycopg.Connection
) -> None:
    token = start_session(client)

    response = client.post(
        "/sessions/verify", headers=auth(token), json={"customer_code": "C-1001", "pin": "0000"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"
    # Proves the refusal was committed, not rolled back with the error.
    row = db.execute(
        "select failed_pin_attempts from customers where customer_code = 'C-1001'"
    ).fetchone()
    assert row == (1,)


def test_three_wrong_pins_lock_the_account(client: TestClient, db: psycopg.Connection) -> None:
    token = start_session(client)

    statuses = [verify(client, token, "C-1001", "0000") for _ in range(3)]
    after_lock = verify(client, token, "C-1001", "2468")

    assert statuses == [401, 401, 423]
    assert after_lock == 423
    row = db.execute("select is_locked from customers where customer_code = 'C-1001'").fetchone()
    assert row == (True,)


def test_unknown_customer_gets_the_same_error_as_a_wrong_pin(client: TestClient) -> None:
    token = start_session(client)

    response = client.post(
        "/sessions/verify", headers=auth(token), json={"customer_code": "C-9999", "pin": "1234"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


def test_requests_without_a_token_are_refused(client: TestClient) -> None:
    response = client.get("/sessions/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "session_invalid"


def test_idle_session_expires(client: TestClient, db: psycopg.Connection) -> None:
    token = start_session(client)
    db.execute(
        "update sessions set expires_at = now() - interval '1 minute' where token = %s",
        (token,),
    )

    response = client.get("/sessions/me", headers=auth(token))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "session_expired"


def test_bad_pin_format_is_not_echoed_back(client: TestClient) -> None:
    token = start_session(client)

    response = client.post(
        "/sessions/verify", headers=auth(token), json={"customer_code": "C-1001", "pin": "98a7"}
    )

    assert response.status_code == 422
    assert "98a7" not in response.text


def test_audit_log_records_attempts_without_the_pin(
    client: TestClient, db: psycopg.Connection
) -> None:
    token = start_session(client)
    verify(client, token, "C-1001", "1111")
    verify(client, token, "C-1001", "2468")

    rows = db.execute("select action, outcome, details::text from audit_log order by id").fetchall()

    actions = [(action, outcome) for action, outcome, _ in rows]
    assert ("session.verify", "denied") in actions
    assert ("session.verify", "allowed") in actions
    assert "1111" not in str(rows)
    assert "2468" not in str(rows)
