"""A row from the sessions table."""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.core.exceptions import VerificationRequired


@dataclass(frozen=True)
class Session:
    """One call. customer_id stays empty until the caller proves who they are."""

    id: UUID
    customer_id: UUID | None
    token: str = field(repr=False)
    verified: bool
    step_up_verified: bool
    last_activity_at: datetime
    expires_at: datetime

    def require_customer_id(self) -> UUID:
        """The verified customer behind this session, or refuse.

        Services call this instead of reading customer_id directly, so no
        banking code can ever run for an unverified caller.
        """
        if not self.verified or self.customer_id is None:
            raise VerificationRequired()
        return self.customer_id
