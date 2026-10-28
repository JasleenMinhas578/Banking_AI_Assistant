"""Response shape for the health check."""

from pydantic import BaseModel


class HealthStatus(BaseModel):
    """What /health returns when everything is fine."""

    status: str
    database: str
