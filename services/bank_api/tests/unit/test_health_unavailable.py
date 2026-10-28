"""The health check must answer 503, not crash, when the database is down.

This needs no database: we point the app at a port where nothing listens.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


def test_health_returns_503_when_database_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings, "database_url", "postgresql://postgres:postgres@127.0.0.1:1/postgres"
    )

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
