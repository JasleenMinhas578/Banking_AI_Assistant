"""Dependency wiring: builds repositories and services for each request.

FastAPI calls these through Depends(). Within one request, get_connection
runs once and every repository shares that same connection and transaction.
"""

from datetime import timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

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
from app.repositories.card_repository import CardRepository
from app.repositories.customer_repository import CustomerRepository
from app.repositories.dispute_repository import DisputeRepository
from app.repositories.health_repository import HealthRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.transaction_repository import TransactionRepository
from app.repositories.transfer_repository import TransferRepository
from app.services.account_service import AccountService
from app.services.card_service import CardService
from app.services.dispute_service import DisputeService
from app.services.health_service import HealthService
from app.services.session_service import SessionService
from app.services.transaction_service import TransactionService
from app.services.transfer_service import TransferLimits, TransferService

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
        otp_ttl=timedelta(minutes=settings.otp_ttl_minutes),
        otp_max_attempts=settings.otp_max_attempts,
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


def get_transaction_service(conn: Connection) -> TransactionService:
    """Build the transaction service for this request."""
    return TransactionService(
        accounts=AccountRepository(conn),
        transactions=TransactionRepository(conn),
        audit=AuditRepository(conn),
    )


def get_card_service(conn: Connection) -> CardService:
    """Build the card service for this request."""
    return CardService(cards=CardRepository(conn), audit=AuditRepository(conn))


def get_dispute_service(conn: Connection) -> DisputeService:
    """Build the dispute service for this request, with the window from settings."""
    return DisputeService(
        transactions=TransactionRepository(conn),
        disputes=DisputeRepository(conn),
        audit=AuditRepository(conn),
        window=timedelta(days=settings.dispute_window_days),
    )


def get_transfer_service(conn: Connection) -> TransferService:
    """Build the transfer service for this request, with POL-004 limits from settings."""
    return TransferService(
        transfers=TransferRepository(conn),
        accounts=AccountRepository(conn),
        audit=AuditRepository(conn),
        limits=TransferLimits(
            per_transfer_cents=settings.per_transfer_limit_cents,
            daily_cents=settings.daily_transfer_limit_cents,
            step_up_threshold_cents=settings.step_up_threshold_cents,
            timezone=ZoneInfo(settings.bank_timezone),
        ),
    )


CurrentSession = Annotated[Session, Depends(get_current_session)]
VerifiedSession = Annotated[Session, Depends(get_verified_session)]
AccountServiceDep = Annotated[AccountService, Depends(get_account_service)]
TransactionServiceDep = Annotated[TransactionService, Depends(get_transaction_service)]
CardServiceDep = Annotated[CardService, Depends(get_card_service)]
DisputeServiceDep = Annotated[DisputeService, Depends(get_dispute_service)]
TransferServiceDep = Annotated[TransferService, Depends(get_transfer_service)]
