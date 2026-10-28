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


def verified_session(client: TestClient, customer_code: str, pin: str) -> str:
    """Start a session and pass the PIN check. Returns the token."""
    token = start_session(client)
    response = client.post(
        "/sessions/verify", headers=auth(token), json={"customer_code": customer_code, "pin": pin}
    )
    assert response.status_code == 200
    return token
