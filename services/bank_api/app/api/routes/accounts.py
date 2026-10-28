"""Account routes: what does the verified caller have, and what happened on it?"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import AccountServiceDep, TransactionServiceDep, VerifiedSession
from app.core.config import settings
from app.schemas.account import AccountList, AccountSummary
from app.schemas.transaction import TransactionList

router = APIRouter(prefix="/accounts", tags=["accounts"])

_PROTECTED = {
    401: {"description": "No valid session, or it timed out"},
    403: {"description": "Session not verified with a PIN yet"},
}


@router.get("", responses=_PROTECTED)
def list_accounts(session: VerifiedSession, service: AccountServiceDep) -> AccountList:
    """List the caller's own accounts with masked numbers and balances."""
    accounts = service.list_accounts(session)
    return AccountList(accounts=[AccountSummary.from_account(a) for a in accounts])


@router.get(
    "/{account_id}/transactions",
    responses={**_PROTECTED, 404: {"description": "No such account for this customer"}},
)
def list_transactions(
    account_id: UUID,
    session: VerifiedSession,
    service: TransactionServiceDep,
    limit: Annotated[
        int, Query(ge=1, le=settings.transactions_max_limit, description="How many to return")
    ] = settings.transactions_default_limit,
) -> TransactionList:
    """Recent transactions on one of the caller's accounts, newest first."""
    account, transactions = service.list_transactions(session, account_id, limit)
    return TransactionList.build(account, transactions)
