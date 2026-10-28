"""/health against the real database."""

from fastapi.testclient import TestClient


def test_health_is_ok_when_database_is_up(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}
