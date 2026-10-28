"""Transfer route: move money between the caller's own accounts.

There is no route to reverse a transfer: POL-004 says the assistant can't.
"""

from typing import Annotated

from fastapi import APIRouter, Header

from app.api.deps import TransferServiceDep, VerifiedSession
from app.schemas.transfer import TransferRequest, TransferResult

router = APIRouter(prefix="/transfers", tags=["transfers"])

IdempotencyKey = Annotated[
    str,
    Header(
        min_length=8,
        max_length=100,
        description="A unique ID the client makes up for each transfer, e.g. a UUID. "
        "Sending the same key again returns the first result instead of moving money twice.",
    ),
]


@router.post(
    "",
    responses={
        401: {"description": "No valid session, or it timed out"},
        403: {"description": "Not verified, or a one-time code is needed (over $1,000)"},
        404: {"description": "One of the accounts isn't yours"},
        409: {"description": "Idempotency-Key already used for a different transfer"},
        422: {"description": "Breaks a rule: limits, balance, or same account"},
    },
)
def create_transfer(
    body: TransferRequest,
    idempotency_key: IdempotencyKey,
    session: VerifiedSession,
    service: TransferServiceDep,
) -> TransferResult:
    """Move money between two of the caller's accounts, after every check passes."""
    outcome = service.transfer(
        session,
        from_account_id=body.from_account_id,
        to_account_id=body.to_account_id,
        amount_cents=body.amount_cents,
        idempotency_key=idempotency_key,
    )
    return TransferResult.from_outcome(outcome)
