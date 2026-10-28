"""Account routes: what does the verified caller have?"""

from fastapi import APIRouter

from app.api.deps import AccountServiceDep, VerifiedSession
from app.schemas.account import AccountList, AccountSummary

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get(
    "",
    responses={
        401: {"description": "No valid session, or it timed out"},
        403: {"description": "Session not verified with a PIN yet"},
    },
)
def list_accounts(session: VerifiedSession, service: AccountServiceDep) -> AccountList:
    """List the caller's own accounts with masked numbers and balances."""
    accounts = service.list_accounts(session)
    return AccountList(accounts=[AccountSummary.from_account(a) for a in accounts])
