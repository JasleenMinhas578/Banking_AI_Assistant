"""Service layer for the health check: decides what 'healthy' means."""

from app.repositories.health_repository import HealthRepository
from app.schemas.health import HealthStatus


class HealthService:
    """Reports whether the API and its database are ready."""

    def __init__(self, repo: HealthRepository) -> None:
        self.repo = repo

    def check(self) -> HealthStatus:
        """Ping the database. If it's down, the repository raises a 503 error."""
        self.repo.ping()
        return HealthStatus(status="ok", database="connected")
