"""Session routes: start a call, verify the PIN, check session status."""

from fastapi import APIRouter, status

from app.api.deps import CurrentSession, SessionServiceDep, SessionToken
from app.core.config import settings
from app.schemas.session import (
    SessionStatus,
    StartSessionResponse,
    StepUpRequest,
    StepUpStarted,
    VerifyRequest,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", status_code=status.HTTP_201_CREATED)
def start_session(service: SessionServiceDep) -> StartSessionResponse:
    """Start a new call. The session is NOT verified yet."""
    return StartSessionResponse.from_new_session(service.start())


@router.post(
    "/verify",
    responses={
        401: {"description": "Wrong customer code or PIN, or no valid session"},
        423: {"description": "Account locked after too many wrong PINs"},
    },
)
def verify_pin(
    body: VerifyRequest, token: SessionToken, service: SessionServiceDep
) -> SessionStatus:
    """Check the caller's customer code and PIN."""
    session = service.verify(token, body.customer_code, body.pin.get_secret_value())
    return SessionStatus.from_session(session)


@router.get("/me")
def session_status(session: CurrentSession) -> SessionStatus:
    """Show whether this session is verified and when it times out."""
    return SessionStatus.from_session(session)


@router.post(
    "/step-up",
    responses={403: {"description": "Verify with your PIN first"}},
)
def start_step_up(token: SessionToken, service: SessionServiceDep) -> StepUpStarted:
    """Send a one-time code, needed for transfers over $1,000. Asking again replaces it."""
    code, expires_at = service.start_step_up(token)
    return StepUpStarted(
        expires_at=expires_at,
        message="A one-time code was sent to your phone.",
        demo_code=code if settings.otp_demo_mode else None,
    )


@router.post(
    "/step-up/verify",
    responses={401: {"description": "Wrong, expired or used-up code"}},
)
def verify_step_up(
    body: StepUpRequest, token: SessionToken, service: SessionServiceDep
) -> SessionStatus:
    """Check the one-time code. Three wrong tries cancel it."""
    session = service.verify_step_up(token, body.code.get_secret_value())
    return SessionStatus.from_session(session)
