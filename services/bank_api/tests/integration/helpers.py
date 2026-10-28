"""Small helpers shared by the integration tests."""

from fastapi.testclient import TestClient


def auth(token: str) -> dict[str, str]:
    """The Authorization header for a session token."""
    return {"Authorization": f"Bearer {token}"}


def start_session(client: TestClient) -> str:
    """Start an unverified session and return its token."""
    response = client.post("/sessions")
    assert response.status_code == 201
    return response.json()["session_token"]


def step_up(client: TestClient, token: str) -> None:
    """Request a one-time code and enter it. Uses demo mode's demo_code."""
    started = client.post("/sessions/step-up", headers=auth(token))
    assert started.status_code == 200
    code = started.json()["demo_code"]
    response = client.post("/sessions/step-up/verify", headers=auth(token), json={"code": code})
    assert response.status_code == 200


def account_ids(client: TestClient, token: str) -> dict[str, str]:
    """The caller's account IDs, keyed by their last 4 digits."""
    accounts = client.get("/accounts", headers=auth(token)).json()["accounts"]
    return {a["masked_number"][-4:]: a["id"] for a in accounts}


def verified_session(client: TestClient, customer_code: str, pin: str) -> str:
    """Start a session and pass the PIN check. Returns the token."""
    token = start_session(client)
    response = client.post(
        "/sessions/verify", headers=auth(token), json={"customer_code": customer_code, "pin": pin}
    )
    assert response.status_code == 200
    return token
