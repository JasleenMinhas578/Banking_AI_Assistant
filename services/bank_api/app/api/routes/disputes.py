"""Dispute routes: challenge one of your purchases, and see your disputes."""

from fastapi import APIRouter

from app.api.deps import DisputeServiceDep, VerifiedSession
from app.schemas.dispute import DisputeList, DisputeResult, DisputeSummary, OpenDisputeRequest

router = APIRouter(prefix="/disputes", tags=["disputes"])

_PROTECTED = {
    401: {"description": "No valid session, or it timed out"},
    403: {"description": "Session not verified with a PIN yet"},
}


@router.get("", responses=_PROTECTED)
def list_disputes(session: VerifiedSession, service: DisputeServiceDep) -> DisputeList:
    """List the caller's disputes, newest first."""
    disputes = service.list_disputes(session)
    return DisputeList(disputes=[DisputeSummary.from_dispute(d) for d in disputes])


@router.post(
    "",
    responses={
        **_PROTECTED,
        404: {"description": "No such transaction for this customer"},
        422: {"description": "Not disputable: too old, still pending, or not a purchase"},
    },
)
def open_dispute(
    body: OpenDisputeRequest, session: VerifiedSession, service: DisputeServiceDep
) -> DisputeResult:
    """Dispute a purchase. If one is already open for it, returns that one."""
    dispute, created = service.open_dispute(session, body.transaction_id, body.reason)
    return DisputeResult.build(dispute, created, service.needs_handoff(dispute))
