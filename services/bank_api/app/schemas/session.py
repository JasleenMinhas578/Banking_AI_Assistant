"""Request and response shapes for sessions."""

import re
from datetime import datetime

from pydantic import BaseModel, Field, SecretStr, field_validator

from app.models.session import Session


class VerifyRequest(BaseModel):
    """What the caller sends to prove who they are."""

    customer_code: str = Field(pattern=r"^C-\d{4}$", examples=["C-1001"])
    # SecretStr prints as '**********', so the PIN can't leak through logs.
    pin: SecretStr = Field(examples=["2468"])

    @field_validator("pin")
    @classmethod
    def pin_is_four_digits(cls, value: SecretStr) -> SecretStr:
        """Reject anything that isn't exactly four digits."""
        if not re.fullmatch(r"\d{4}", value.get_secret_value()):
            raise ValueError("PIN must be exactly 4 digits")
        return value


class SessionStatus(BaseModel):
    """The current state of a session. Never includes the token or PIN."""

    verified: bool
    step_up_verified: bool
    expires_at: datetime

    @classmethod
    def from_session(cls, session: Session) -> "SessionStatus":
        """Build the public view of a session."""
        return cls(
            verified=session.verified,
            step_up_verified=session.step_up_verified,
            expires_at=session.expires_at,
        )


class StartSessionResponse(SessionStatus):
    """Returned once, when a call starts. The client keeps the token."""

    session_token: str

    @classmethod
    def from_new_session(cls, session: Session) -> "StartSessionResponse":
        """Build the response for a brand-new session, including its token."""
        return cls(
            session_token=session.token,
            verified=session.verified,
            step_up_verified=session.step_up_verified,
            expires_at=session.expires_at,
        )


class StepUpStarted(BaseModel):
    """A one-time code was issued. In a real bank it would go to the customer's phone."""

    expires_at: datetime
    message: str = Field(examples=["A one-time code was sent to your phone."])
    demo_code: str | None = Field(
        default=None,
        description="Only filled in demo mode (OTP_DEMO_MODE), because there's no SMS here.",
    )


class StepUpRequest(BaseModel):
    """The one-time code the caller received."""

    code: SecretStr = Field(examples=["048213"])

    @field_validator("code")
    @classmethod
    def code_is_six_digits(cls, value: SecretStr) -> SecretStr:
        """Reject anything that isn't exactly six digits."""
        if not re.fullmatch(r"\d{6}", value.get_secret_value()):
            raise ValueError("The code must be exactly 6 digits")
        return value
