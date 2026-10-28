"""Dependency wiring: builds repositories and services for each request.

FastAPI calls these through Depends(). Within one request, get_connection
runs once and every repository shares that same connection and transaction.
"""

from datetime import timedelta
from typing import Annotated

import psycopg
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.database import get_connection
from app.core.exceptions import SessionInvalid
from app.core.security import PinVerifier
from app.models.session import Session
from app.repositories.account_repository import AccountRepository
from app.repositories.audit_repository import AuditRepository
from app.repositories.customer_repository import CustomerRepository
from app.repositories.health_repository import HealthRepository
from app.repositories.session_repository import SessionRepository
from app.services.account_service import AccountService
from app.services.health_service import HealthService
from app.services.session_service import SessionService

Connection = Annotated[psycopg.Connection, Depends(get_connection)]

# Reads "Authorization: Bearer <token>". auto_error=False lets us return our
# own error shape instead of FastAPI's default.
_bearer = HTTPBearer(auto_error=False)


def get_health_service(conn: Connection) -> HealthService:
    """Build the health service for this request."""
    return HealthService(HealthRepository(conn))


def get_session_service(conn: Connection) -> SessionService:
    """Build the session service for this request, with limits from settings."""
    return SessionService(
        sessions=SessionRepository(conn),
        customers=CustomerRepository(conn),
        audit=AuditRepository(conn),
        pins=PinVerifier(),
        max_pin_attempts=settings.max_pin_attempts,
        idle_timeout=timedelta(minutes=settings.session_idle_minutes),
    )


def get_session_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> str:
    """Pull the session token out of the Authorization header."""
    if credentials is None:
        raise SessionInvalid()
    return credentials.credentials


HealthServiceDep = Annotated[HealthService, Depends(get_health_service)]
SessionServiceDep = Annotated[SessionService, Depends(get_session_service)]
SessionToken = Annotated[str, Depends(get_session_token)]


def get_current_session(token: SessionToken, service: SessionServiceDep) -> Session:
    """The live session for this request, verified or not."""
    return service.require_active(token)


def get_verified_session(token: SessionToken, service: SessionServiceDep) -> Session:
    """A live session whose caller passed the PIN check. Banking endpoints use this."""
    return service.require_verified(token)


def get_account_service(conn: Connection) -> AccountService:
    """Build the account service for this request."""
    return AccountService(accounts=AccountRepository(conn), audit=AuditRepository(conn))


CurrentSession = Annotated[Session, Depends(get_current_session)]
VerifiedSession = Annotated[Session, Depends(get_verified_session)]
AccountServiceDep = Annotated[AccountService, Depends(get_account_service)]
