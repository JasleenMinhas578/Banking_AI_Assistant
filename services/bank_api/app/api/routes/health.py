"""Route layer for the health check: HTTP in, HTTP out, no logic."""

from fastapi import APIRouter

from app.api.deps import HealthServiceDep
from app.schemas.health import HealthStatus

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    responses={503: {"description": "The database is not reachable"}},
)
def health(service: HealthServiceDep) -> HealthStatus:
    """Return 200 if the API can reach its database, 503 if not."""
    return service.check()
